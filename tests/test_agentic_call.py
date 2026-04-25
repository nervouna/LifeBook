"""Tests for agentic_call, web_search, and _discuss integration."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from lifebook.config import Config, KnowledgeConfig, LLMConfig, TavilyConfig, FeishuConfig, ExecutorConfig, DigestConfig, FetchConfig, LoggingConfig
from lifebook.llm import LLMClient
from lifebook.notes import now_iso
from lifebook.fetcher import WEB_SEARCH_TOOL, web_search
from lifebook.writer import UPDATE_DRAFT_TOOL


# ---- helpers ----

def _tool_use_block(name: str, input_data: dict, tc_id: str = "tc_1"):
    return SimpleNamespace(
        type="tool_use",
        id=tc_id,
        name=name,
        input=input_data,
    )


def _text_block(text: str):
    return SimpleNamespace(type="text", text=text)


def _response(content_blocks, stop_reason="end_turn"):
    return SimpleNamespace(content=content_blocks, stop_reason=stop_reason)


def _make_llm():
    """Create LLMClient with mocked Anthropic client."""
    cfg = LLMConfig(api_key="fake", base_url="https://fake.api")
    with patch("lifebook.llm.anthropic.Anthropic"):
        client = LLMClient(cfg)
    return client


def _make_cfg(tmp_path):
    return Config(
        knowledge=KnowledgeConfig(root=tmp_path),
        llm=LLMConfig(api_key="fake", base_url="https://fake.api"),
        feishu=FeishuConfig(),
        executor=ExecutorConfig(),
        digest=DigestConfig(),
        tavily=TavilyConfig(api_key="tavily-fake"),
        fetch=FetchConfig(),
        logging=LoggingConfig(),
    )


# ---- agentic_call tests ----

class TestAgenticCall:
    def test_no_tool_use(self):
        """LLM returns text immediately without tool calls."""
        llm = _make_llm()
        llm.client.messages.create.return_value = _response([_text_block("Hello world")])

        result = llm.agentic_call(
            system="sys", messages=[{"role": "user", "content": "hi"}],
            tools=[WEB_SEARCH_TOOL], tool_executor={},
        )
        assert result == "Hello world"
        assert llm.client.messages.create.call_count == 1

    def test_one_round_tool_use(self):
        """LLM calls tool once, gets result, returns text."""
        llm = _make_llm()
        llm.client.messages.create.side_effect = [
            _response([_tool_use_block("web_search", {"query": "test"}, "t1")], stop_reason="tool_use"),
            _response([_text_block("Found info")]),
        ]
        executor = {"web_search": MagicMock(return_value="search result")}

        result = llm.agentic_call(
            system="sys", messages=[{"role": "user", "content": "hi"}],
            tools=[WEB_SEARCH_TOOL], tool_executor=executor,
        )
        assert result == "Found info"
        executor["web_search"].assert_called_once_with({"query": "test"})
        assert llm.client.messages.create.call_count == 2

    def test_multiple_tool_blocks(self):
        """LLM emits multiple tool calls in one response."""
        llm = _make_llm()
        llm.client.messages.create.side_effect = [
            _response([
                _tool_use_block("web_search", {"query": "q1"}, "t1"),
                _tool_use_block("web_search", {"query": "q2"}, "t2"),
            ], stop_reason="tool_use"),
            _response([_text_block("Combined result")]),
        ]
        executor = {"web_search": MagicMock(return_value="res")}

        result = llm.agentic_call(
            system="sys", messages=[{"role": "user", "content": "hi"}],
            tools=[WEB_SEARCH_TOOL], tool_executor=executor,
        )
        assert result == "Combined result"
        assert executor["web_search"].call_count == 2

    def test_max_rounds_exceeded(self):
        """After max_rounds of tool calls, forces text output."""
        llm = _make_llm()
        llm.client.messages.create.side_effect = [
            _response([_tool_use_block("web_search", {"query": "q"}, "t1")], stop_reason="tool_use"),
            _response([_tool_use_block("web_search", {"query": "q"}, "t2")], stop_reason="tool_use"),
            _response([_text_block("Final answer")]),
        ]
        executor = {"web_search": MagicMock(return_value="res")}

        result = llm.agentic_call(
            system="sys", messages=[{"role": "user", "content": "hi"}],
            tools=[WEB_SEARCH_TOOL], tool_executor=executor, max_rounds=2,
        )
        assert result == "Final answer"
        # Last call should not have tools
        last_call_kwargs = llm.client.messages.create.call_args
        assert "tools" not in last_call_kwargs.kwargs


# ---- web_search tests ----

class TestWebSearch:
    def test_success(self, tmp_path):
        cfg = _make_cfg(tmp_path)
        mock_client = MagicMock()
        mock_client.search.return_value = {
            "results": [
                {"title": "Title1", "url": "http://example.com", "content": "Snippet1"},
            ]
        }

        with patch("lifebook.fetcher.TavilyClient", return_value=mock_client):
            result = web_search("test query", cfg)

        assert "Title1" in result
        assert "http://example.com" in result
        mock_client.search.assert_called_once_with(query="test query", max_results=5)

    def test_error(self, tmp_path):
        cfg = _make_cfg(tmp_path)
        mock_client = MagicMock()
        mock_client.search.side_effect = Exception("timeout")

        with patch("lifebook.fetcher.TavilyClient", return_value=mock_client):
            result = web_search("test", cfg)
        assert "搜索失败" in result

    def test_no_api_key(self, tmp_path):
        cfg = _make_cfg(tmp_path)
        cfg.tavily.api_key = ""
        result = web_search("test", cfg)
        assert "API key" in result


# ---- _discuss integration test ----

def _create_discuss_draft(writer, stage="content", title="test", checklist=""):
    """Create draft.json + draft.md for _discuss tests."""
    writer.draft_meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta = {
        "stage": stage,
        "title": title,
        "created": now_iso(),
        "updated": now_iso(),
        "concept": {"concept_text": "Test concept"},
        "checklist": checklist,
    }
    writer.draft_meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    writer.draft_path.write_text("Original content", encoding="utf-8")


class TestDiscussIntegration:
    def test_discuss_uses_agentic_call(self, tmp_path):
        """_discuss should call agentic_call instead of text_call."""
        cfg = _make_cfg(tmp_path)

        with patch("lifebook.llm.anthropic.Anthropic"):
            llm = LLMClient(cfg.llm)

        llm.agentic_call = MagicMock(return_value="## Updated content\n\nNew text")

        from lifebook.writer import Writer, STAGE_CONTENT

        writer = Writer(cfg, llm)
        _create_discuss_draft(writer, stage=STAGE_CONTENT)

        result = writer._discuss("请修改第一段")

        llm.agentic_call.assert_called_once()
        call_kwargs = llm.agentic_call.call_args
        assert call_kwargs.kwargs.get("tools") or (call_kwargs.args and len(call_kwargs.args) > 2)

    def test_discuss_passes_both_tools(self, tmp_path):
        """_discuss should pass both web_search and update_draft tools."""
        cfg = _make_cfg(tmp_path)

        with patch("lifebook.llm.anthropic.Anthropic"):
            llm = LLMClient(cfg.llm)

        llm.agentic_call = MagicMock(return_value="讨论内容")

        from lifebook.writer import Writer, STAGE_CONTENT

        writer = Writer(cfg, llm)
        _create_discuss_draft(writer, stage=STAGE_CONTENT)

        writer._discuss("请修改第一段")

        call_kwargs = llm.agentic_call.call_args.kwargs
        tools = call_kwargs["tools"]
        tool_names = {t["name"] for t in tools}
        assert "web_search" in tool_names
        assert "update_draft" in tool_names

    def test_discuss_update_draft_tool_updates_file(self, tmp_path):
        """When LLM calls update_draft, draft file gets updated and history has only discussion text."""
        cfg = _make_cfg(tmp_path)

        with patch("lifebook.llm.anthropic.Anthropic"):
            llm = LLMClient(cfg.llm)

        from lifebook.writer import Writer, STAGE_CONTENT, STAGE_REVIEW

        writer = Writer(cfg, llm)
        _create_discuss_draft(writer, stage=STAGE_CONTENT, checklist="- old item")

        # Mock agentic_call to simulate tool execution by calling the executor directly
        def fake_agentic_call(system, messages, tools, tool_executor, **kwargs):
            tool_executor["update_draft"]({"content": "Updated article content", "checklist": "- 新清单项"})
            return "我已经修改了文章内容。"

        llm.agentic_call = MagicMock(side_effect=fake_agentic_call)

        result = writer._discuss("请修改内容")

        assert result == "我已经修改了文章内容。"

        assert len(writer._history) == 2
        assert writer._history[0] == {"role": "user", "content": "请修改内容"}
        assert writer._history[1] == {"role": "assistant", "content": "我已经修改了文章内容。"}
        assert "Updated article content" not in writer._history[1]["content"]

        # Verify draft.json was updated
        meta, content = writer._load_draft()
        assert meta["stage"] == STAGE_REVIEW
        assert meta["checklist"] == "- 新清单项"
        assert "Updated article content" in content
