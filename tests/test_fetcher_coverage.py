"""Coverage tests for fetcher.py and llm.py."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


class TestFetcherHelpers:
    def test_domain(self):
        from lifebook.fetcher import _domain
        assert _domain("https://www.Example.com/path") == "example.com"

    def test_domain_no_host(self):
        from lifebook.fetcher import _domain
        assert _domain("not-a-url") == ""

    def test_should_skip(self):
        from lifebook.fetcher import _should_skip
        assert _should_skip("https://blocked.com/page", ["blocked.com"]) is True
        assert _should_skip("https://ok.com/page", ["blocked.com"]) is False

    def test_should_skip_subdomain(self):
        from lifebook.fetcher import _should_skip
        assert _should_skip("https://sub.blocked.com/page", ["blocked.com"]) is True

    def test_extract_title_from_markdown(self):
        from lifebook.fetcher import _extract_title_from_markdown
        assert _extract_title_from_markdown("# My Title\nBody") == "My Title"

    def test_extract_title_none(self):
        from lifebook.fetcher import _extract_title_from_markdown
        assert _extract_title_from_markdown("no title here") is None


class TestFetcherFetch:
    def test_skip_domain(self):
        from lifebook.fetcher import Fetcher
        from lifebook.config import TavilyConfig, FetchConfig
        f = Fetcher(TavilyConfig(), FetchConfig(skip_domains=["blocked.com"]))
        result = f.fetch("https://blocked.com/page")
        assert result.ok is False
        assert result.status == "needs_clip"

    def test_tavily_success(self):
        from lifebook.fetcher import Fetcher
        from lifebook.config import TavilyConfig, FetchConfig
        f = Fetcher(TavilyConfig(api_key="fake"), FetchConfig())
        mock_client = MagicMock()
        mock_client.extract.return_value = {
            "results": [{"raw_content": "content here", "title": "Title"}],
            "failed_results": [],
        }
        f._tavily = mock_client
        result = f.fetch("https://example.com")
        assert result.ok is True
        assert result.via == "tavily"

    def test_tavily_empty_results_fallback_disabled(self):
        from lifebook.fetcher import Fetcher
        from lifebook.config import TavilyConfig, FetchConfig
        f = Fetcher(TavilyConfig(api_key="fake"), FetchConfig(enable_fallback=False))
        mock_client = MagicMock()
        mock_client.extract.return_value = {"results": [], "failed_results": []}
        f._tavily = mock_client
        result = f.fetch("https://example.com")
        assert result.ok is False

    def test_tavily_empty_content_fallback_disabled(self):
        from lifebook.fetcher import Fetcher
        from lifebook.config import TavilyConfig, FetchConfig
        f = Fetcher(TavilyConfig(api_key="fake"), FetchConfig(enable_fallback=False))
        mock_client = MagicMock()
        mock_client.extract.return_value = {
            "results": [{"raw_content": "   ", "title": "T"}],
            "failed_results": [],
        }
        f._tavily = mock_client
        result = f.fetch("https://example.com")
        assert result.ok is False

    def test_tavily_exception_fallback_disabled(self):
        from lifebook.fetcher import Fetcher
        from lifebook.config import TavilyConfig, FetchConfig
        f = Fetcher(TavilyConfig(api_key="fake"), FetchConfig(enable_fallback=False))
        mock_client = MagicMock()
        mock_client.extract.side_effect = Exception("timeout")
        f._tavily = mock_client
        result = f.fetch("https://example.com")
        assert result.ok is False

    def test_tavily_title_from_markdown(self):
        from lifebook.fetcher import Fetcher
        from lifebook.config import TavilyConfig, FetchConfig
        f = Fetcher(TavilyConfig(api_key="fake"), FetchConfig())
        mock_client = MagicMock()
        mock_client.extract.return_value = {
            "results": [{"raw_content": "# MD Title\ncontent", "title": None}],
            "failed_results": [],
        }
        f._tavily = mock_client
        result = f.fetch("https://example.com")
        assert result.title == "MD Title"

    def test_no_tavily_no_fallback(self):
        from lifebook.fetcher import Fetcher
        from lifebook.config import TavilyConfig, FetchConfig
        f = Fetcher(TavilyConfig(), FetchConfig(enable_fallback=False))
        f._tavily = None
        result = f.fetch("https://example.com")
        assert result.ok is False
        assert "fallback disabled" in result.error

    def test_httpx_fallback_success(self):
        """Lines 100-125: httpx fetch with readability succeeds."""
        import sys
        from lifebook.fetcher import Fetcher
        from lifebook.config import TavilyConfig, FetchConfig

        # Create mock readability and bs4 modules
        mock_readability = MagicMock()
        mock_doc = MagicMock()
        mock_doc.short_title.return_value = "Page Title"
        mock_doc.summary.return_value = "<p>Content here</p>"
        mock_readability.Document.return_value = mock_doc

        mock_bs4 = MagicMock()
        mock_bs4.BeautifulSoup.return_value.get_text.return_value = "Content here"

        saved = {}
        for name, mod in [("readability", mock_readability), ("bs4", mock_bs4)]:
            if name in sys.modules:
                saved[name] = sys.modules[name]
            sys.modules[name] = mod

        try:
            f = Fetcher(TavilyConfig(), FetchConfig(enable_fallback=True))
            f._tavily = None

            mock_resp = MagicMock()
            mock_resp.text = "<html><body>Content</body></html>"
            mock_resp.raise_for_status = MagicMock()

            mock_client_ctx = MagicMock()
            mock_client_ctx.__enter__ = MagicMock(return_value=mock_client_ctx)
            mock_client_ctx.__exit__ = MagicMock(return_value=False)
            mock_client_ctx.get.return_value = mock_resp

            with patch("lifebook.fetcher.httpx.Client", return_value=mock_client_ctx):
                result = f.fetch("https://example.com")
            assert result.ok is True
            assert result.via == "httpx"
        finally:
            for name in ["readability", "bs4"]:
                if name in saved:
                    sys.modules[name] = saved[name]
                else:
                    sys.modules.pop(name, None)

    def test_httpx_fallback_empty_content(self):
        """Lines 117-121: readability produces empty content."""
        import sys
        from lifebook.fetcher import Fetcher
        from lifebook.config import TavilyConfig, FetchConfig

        mock_readability = MagicMock()
        mock_doc = MagicMock()
        mock_doc.short_title.return_value = "Title"
        mock_doc.summary.return_value = "<p></p>"
        mock_readability.Document.return_value = mock_doc

        mock_bs4 = MagicMock()
        mock_bs4.BeautifulSoup.return_value.get_text.return_value = "  "

        saved = {}
        for name, mod in [("readability", mock_readability), ("bs4", mock_bs4)]:
            if name in sys.modules:
                saved[name] = sys.modules[name]
            sys.modules[name] = mod

        try:
            f = Fetcher(TavilyConfig(), FetchConfig(enable_fallback=True))
            f._tavily = None

            mock_resp = MagicMock()
            mock_resp.text = "<html></html>"
            mock_resp.raise_for_status = MagicMock()

            mock_client_ctx = MagicMock()
            mock_client_ctx.__enter__ = MagicMock(return_value=mock_client_ctx)
            mock_client_ctx.__exit__ = MagicMock(return_value=False)
            mock_client_ctx.get.return_value = mock_resp

            with patch("lifebook.fetcher.httpx.Client", return_value=mock_client_ctx):
                result = f.fetch("https://example.com")
            assert result.ok is False
        finally:
            for name in ["readability", "bs4"]:
                if name in saved:
                    sys.modules[name] = saved[name]
                else:
                    sys.modules.pop(name, None)

    def test_httpx_fallback_exception(self):
        from lifebook.fetcher import Fetcher
        from lifebook.config import TavilyConfig, FetchConfig
        f = Fetcher(TavilyConfig(), FetchConfig(enable_fallback=True))
        f._tavily = None

        mock_client_ctx = MagicMock()
        mock_client_ctx.__enter__ = MagicMock(return_value=mock_client_ctx)
        mock_client_ctx.__exit__ = MagicMock(return_value=False)
        mock_client_ctx.get.side_effect = Exception("conn error")

        with patch("lifebook.fetcher.httpx.Client", return_value=mock_client_ctx):
            result = f.fetch("https://example.com")
        assert result.ok is False
        assert result.via == "httpx"


class TestWebSearchFetcher:
    def test_web_search_no_results(self, tmp_path):
        from lifebook.fetcher import web_search
        from lifebook.config import Config, KnowledgeConfig, LLMConfig, TavilyConfig
        cfg = Config(
            knowledge=KnowledgeConfig(root=tmp_path), llm=LLMConfig(),
            feishu=MagicMock(), executor=MagicMock(), digest=MagicMock(),
            tavily=TavilyConfig(api_key="fake"), fetch=MagicMock(), logging=MagicMock(),
        )
        mock_client = MagicMock()
        mock_client.search.return_value = {"results": []}
        with patch("lifebook.fetcher.TavilyClient", return_value=mock_client):
            result = web_search("test", cfg)
        assert "没有找到" in result

    def test_web_search_error(self, tmp_path):
        from lifebook.fetcher import web_search
        from lifebook.config import Config, KnowledgeConfig, LLMConfig, TavilyConfig
        cfg = Config(
            knowledge=KnowledgeConfig(root=tmp_path), llm=LLMConfig(),
            feishu=MagicMock(), executor=MagicMock(), digest=MagicMock(),
            tavily=TavilyConfig(api_key="fake"), fetch=MagicMock(), logging=MagicMock(),
        )
        mock_client = MagicMock()
        mock_client.search.side_effect = Exception("fail")
        with patch("lifebook.fetcher.TavilyClient", return_value=mock_client):
            result = web_search("test", cfg)
        assert "搜索失败" in result

    def test_web_search_no_api_key(self, tmp_path):
        from lifebook.fetcher import web_search
        from lifebook.config import Config, KnowledgeConfig, LLMConfig, TavilyConfig
        cfg = Config(
            knowledge=KnowledgeConfig(root=tmp_path), llm=LLMConfig(),
            feishu=MagicMock(), executor=MagicMock(), digest=MagicMock(),
            tavily=TavilyConfig(api_key=""), fetch=MagicMock(), logging=MagicMock(),
        )
        result = web_search("test", cfg)
        assert "未配置" in result

    def test_web_search_success(self, tmp_path):
        from lifebook.fetcher import web_search
        from lifebook.config import Config, KnowledgeConfig, LLMConfig, TavilyConfig
        cfg = Config(
            knowledge=KnowledgeConfig(root=tmp_path), llm=LLMConfig(),
            feishu=MagicMock(), executor=MagicMock(), digest=MagicMock(),
            tavily=TavilyConfig(api_key="fake"), fetch=MagicMock(), logging=MagicMock(),
        )
        mock_client = MagicMock()
        mock_client.search.return_value = {
            "results": [{"title": "T1", "url": "http://a.com", "content": "c1"}],
        }
        with patch("lifebook.fetcher.TavilyClient", return_value=mock_client):
            result = web_search("test", cfg)
        assert "T1" in result
        assert "http://a.com" in result


class TestLLMCoverage:
    def test_parse_tool_calls_from_content(self):
        from lifebook.llm import _parse_tool_calls_from_content
        content = '<｜DSML｜invoke name="extract_note"><｜DSML｜parameter name="title">Test</｜DSML｜parameter></｜DSML｜invoke>'
        result = _parse_tool_calls_from_content(content)
        assert len(result) == 1
        assert result[0]["name"] == "extract_note"

    def test_parse_tool_calls_empty(self):
        from lifebook.llm import _parse_tool_calls_from_content
        assert _parse_tool_calls_from_content("no tool calls") == []

    def test_to_anthropic_tool(self):
        from lifebook.llm import _to_anthropic_tool
        tool = {"name": "test", "description": "desc", "input_schema": {"type": "object"}}
        result = _to_anthropic_tool(tool)
        assert result["name"] == "test"

    def test_parse_response(self):
        from lifebook.llm import _parse_response
        blocks = [
            SimpleNamespace(type="tool_use", id="t1", name="test", input={"k": "v"}),
            SimpleNamespace(type="text", text="hello"),
        ]
        response = SimpleNamespace(content=blocks)
        tool_uses, text = _parse_response(response)
        assert len(tool_uses) == 1
        assert text == "hello"

    def test_structured_call_no_system(self):
        from lifebook.llm import LLMClient
        from lifebook.config import LLMConfig
        cfg = LLMConfig(api_key="fake", base_url="https://fake.api")
        with patch("lifebook.llm.anthropic.Anthropic"):
            client = LLMClient(cfg)
        mock_block = SimpleNamespace(type="tool_use", id="t1", name="extract", input={"result": "ok"})
        client.client.messages.create.return_value = SimpleNamespace(
            content=[mock_block], stop_reason="tool_use",
        )
        result = client.structured_call(
            tool_name="extract", tool_description="desc",
            input_schema={}, user_prompt="prompt",
        )
        assert result == {"result": "ok"}
        call_kwargs = client.client.messages.create.call_args.kwargs
        assert "system" not in call_kwargs

    def test_text_call_with_messages(self):
        from lifebook.llm import LLMClient
        from lifebook.config import LLMConfig
        cfg = LLMConfig(api_key="fake", base_url="https://fake.api")
        with patch("lifebook.llm.anthropic.Anthropic"):
            client = LLMClient(cfg)
        client.client.messages.create.return_value = SimpleNamespace(
            content=[SimpleNamespace(type="text", text="response")],
        )
        result = client.text_call(messages=[{"role": "user", "content": "hi"}])
        assert result == "response"

    def test_text_call_neither_prompt_nor_messages(self):
        from lifebook.llm import LLMClient
        from lifebook.config import LLMConfig
        cfg = LLMConfig(api_key="fake", base_url="https://fake.api")
        with patch("lifebook.llm.anthropic.Anthropic"):
            client = LLMClient(cfg)
        with pytest.raises(ValueError, match="Either"):
            client.text_call()

    def test_structured_call_retry_then_success(self):
        from lifebook.llm import LLMClient
        from lifebook.config import LLMConfig
        cfg = LLMConfig(api_key="fake", base_url="https://fake.api")
        with patch("lifebook.llm.anthropic.Anthropic"):
            client = LLMClient(cfg)
        no_tool = SimpleNamespace(content=[SimpleNamespace(type="text", text="oops")], stop_reason="end_turn")
        has_tool = SimpleNamespace(
            content=[SimpleNamespace(type="tool_use", id="t1", name="extract", input={"ok": True})],
            stop_reason="tool_use",
        )
        client.client.messages.create.side_effect = [no_tool, has_tool]
        result = client.structured_call(
            tool_name="extract", tool_description="desc",
            input_schema={}, user_prompt="prompt", max_retries=1,
        )
        assert result == {"ok": True}

    def test_structured_call_xml_fallback(self):
        from lifebook.llm import LLMClient
        from lifebook.config import LLMConfig
        cfg = LLMConfig(api_key="fake", base_url="https://fake.api")
        with patch("lifebook.llm.anthropic.Anthropic"):
            client = LLMClient(cfg)
        xml = '<｜DSML｜invoke name="extract"><｜DSML｜parameter name="title">XML Title</｜DSML｜parameter></｜DSML｜invoke>'
        client.client.messages.create.return_value = SimpleNamespace(
            content=[SimpleNamespace(type="text", text=xml)],
            stop_reason="end_turn",
        )
        result = client.structured_call(
            tool_name="extract", tool_description="desc",
            input_schema={}, user_prompt="prompt", max_retries=0,
        )
        assert result == {"title": "XML Title"}

    def test_structured_call_all_retries_fail(self):
        from lifebook.llm import LLMClient
        from lifebook.config import LLMConfig
        cfg = LLMConfig(api_key="fake", base_url="https://fake.api")
        with patch("lifebook.llm.anthropic.Anthropic"):
            client = LLMClient(cfg)
        client.client.messages.create.return_value = SimpleNamespace(
            content=[SimpleNamespace(type="text", text="no tools")],
            stop_reason="end_turn",
        )
        with pytest.raises(RuntimeError, match="failed after"):
            client.structured_call(
                tool_name="extract", tool_description="desc",
                input_schema={}, user_prompt="prompt", max_retries=0,
            )

    def test_agentic_call_unknown_tool(self):
        from lifebook.llm import LLMClient
        from lifebook.config import LLMConfig
        cfg = LLMConfig(api_key="fake", base_url="https://fake.api")
        with patch("lifebook.llm.anthropic.Anthropic"):
            client = LLMClient(cfg)
        client.client.messages.create.side_effect = [
            SimpleNamespace(
                content=[SimpleNamespace(type="tool_use", id="t1", name="unknown_tool", input={})],
                stop_reason="tool_use",
            ),
            SimpleNamespace(content=[SimpleNamespace(type="text", text="done")]),
        ]
        result = client.agentic_call(
            system="sys",
            messages=[{"role": "user", "content": "hi"}],
            tools=[{"name": "web_search", "description": "d", "input_schema": {}}],
            tool_executor={},
        )
        assert result == "done"

    def test_agentic_call_xml_tool_unknown(self):
        from lifebook.llm import LLMClient
        from lifebook.config import LLMConfig
        cfg = LLMConfig(api_key="fake", base_url="https://fake.api")
        with patch("lifebook.llm.anthropic.Anthropic"):
            client = LLMClient(cfg)
        xml = '<｜DSML｜invoke name="unknown_xml_tool"><｜DSML｜parameter name="q">test</｜DSML｜parameter></｜DSML｜invoke>'
        client.client.messages.create.side_effect = [
            SimpleNamespace(content=[SimpleNamespace(type="text", text=xml)], stop_reason="end_turn"),
            SimpleNamespace(content=[SimpleNamespace(type="text", text="result")]),
        ]
        result = client.agentic_call(
            system="sys",
            messages=[{"role": "user", "content": "hi"}],
            tools=[{"name": "known", "description": "d", "input_schema": {}}],
            tool_executor={},
        )
        assert result == "result"

    def test_strip_auth_middleware(self):
        from lifebook.llm import _StripAuthMiddleware
        mock_transport = MagicMock()
        mock_transport.handle_request.return_value = MagicMock()
        mw = _StripAuthMiddleware(mock_transport)
        req = MagicMock()
        req.headers = {"authorization": "Bearer token", "other": "val"}
        mw.handle_request(req)
        assert "authorization" not in req.headers

    def test_extra_headers(self):
        from lifebook.llm import LLMClient
        from lifebook.config import LLMConfig
        cfg = LLMConfig(api_key="fake", base_url="https://fake.api", extra_headers={"X-Custom": "val"})
        with patch("lifebook.llm.anthropic.Anthropic") as MockAnthropic:
            LLMClient(cfg)
        call_kwargs = MockAnthropic.call_args.kwargs
        assert call_kwargs["default_headers"] == {"X-Custom": "val"}

    def test_structured_call_with_system(self):
        from lifebook.llm import LLMClient
        from lifebook.config import LLMConfig
        cfg = LLMConfig(api_key="fake", base_url="https://fake.api")
        with patch("lifebook.llm.anthropic.Anthropic"):
            client = LLMClient(cfg)
        mock_block = SimpleNamespace(type="tool_use", id="t1", name="extract", input={"result": "ok"})
        client.client.messages.create.return_value = SimpleNamespace(
            content=[mock_block], stop_reason="tool_use",
        )
        client.structured_call(
            tool_name="extract", tool_description="desc",
            input_schema={}, user_prompt="prompt", system="system prompt",
        )
        call_kwargs = client.client.messages.create.call_args.kwargs
        assert call_kwargs["system"] == [
            {"type": "text", "text": "system prompt", "cache_control": {"type": "ephemeral"}},
        ]

    def test_structured_call_empty_tool_use_input(self):
        from lifebook.llm import LLMClient
        from lifebook.config import LLMConfig
        cfg = LLMConfig(api_key="fake", base_url="https://fake.api")
        with patch("lifebook.llm.anthropic.Anthropic"):
            client = LLMClient(cfg)
        empty_input = SimpleNamespace(type="tool_use", id="t1", name="extract", input={})
        good_input = SimpleNamespace(type="tool_use", id="t2", name="extract", input={"ok": True})
        client.client.messages.create.side_effect = [
            SimpleNamespace(content=[empty_input], stop_reason="tool_use"),
            SimpleNamespace(content=[good_input], stop_reason="tool_use"),
        ]
        result = client.structured_call(
            tool_name="extract", tool_description="desc",
            input_schema={}, user_prompt="prompt", max_retries=1,
        )
        assert result == {"ok": True}

    def test_structured_call_empty_xml_args(self):
        from lifebook.llm import LLMClient
        from lifebook.config import LLMConfig
        cfg = LLMConfig(api_key="fake", base_url="https://fake.api")
        with patch("lifebook.llm.anthropic.Anthropic"):
            client = LLMClient(cfg)
        xml_empty = '<｜DSML｜invoke name="extract"></｜DSML｜invoke>'
        xml_good = '<｜DSML｜invoke name="extract"><｜DSML｜parameter name="k">val</｜DSML｜parameter></｜DSML｜invoke>'
        client.client.messages.create.side_effect = [
            SimpleNamespace(content=[SimpleNamespace(type="text", text=xml_empty)], stop_reason="end_turn"),
            SimpleNamespace(content=[SimpleNamespace(type="text", text=xml_good)], stop_reason="end_turn"),
        ]
        result = client.structured_call(
            tool_name="extract", tool_description="desc",
            input_schema={}, user_prompt="prompt", max_retries=1,
        )
        assert result == {"k": "val"}

    def test_text_call_with_user_prompt(self):
        from lifebook.llm import LLMClient
        from lifebook.config import LLMConfig
        cfg = LLMConfig(api_key="fake", base_url="https://fake.api")
        with patch("lifebook.llm.anthropic.Anthropic"):
            client = LLMClient(cfg)
        client.client.messages.create.return_value = SimpleNamespace(
            content=[SimpleNamespace(type="text", text="response text")],
        )
        result = client.text_call(user_prompt="hello", system="sys prompt")
        assert result == "response text"
        call_kwargs = client.client.messages.create.call_args.kwargs
        assert call_kwargs["system"] == [
            {"type": "text", "text": "sys prompt", "cache_control": {"type": "ephemeral"}},
        ]

    def test_agentic_call_xml_tool_with_executor(self):
        from lifebook.llm import LLMClient
        from lifebook.config import LLMConfig
        cfg = LLMConfig(api_key="fake", base_url="https://fake.api")
        with patch("lifebook.llm.anthropic.Anthropic"):
            client = LLMClient(cfg)
        xml = '<｜DSML｜invoke name="search"><｜DSML｜parameter name="q">test</｜DSML｜parameter></｜DSML｜invoke>'
        client.client.messages.create.side_effect = [
            SimpleNamespace(content=[SimpleNamespace(type="text", text=xml)], stop_reason="end_turn"),
            SimpleNamespace(content=[SimpleNamespace(type="text", text="final result")]),
        ]
        mock_executor = MagicMock(return_value="search results")
        result = client.agentic_call(
            system="sys",
            messages=[{"role": "user", "content": "hi"}],
            tools=[{"name": "search", "description": "d", "input_schema": {}}],
            tool_executor={"search": mock_executor},
        )
        assert result == "final result"
        mock_executor.assert_called_once()

    def test_agentic_call_xml_tool_in_names_but_no_executor(self):
        """Lines 231-232: XML tool in tool_names but not in tool_executor dict."""
        from lifebook.llm import LLMClient
        from lifebook.config import LLMConfig
        cfg = LLMConfig(api_key="fake", base_url="https://fake.api")
        with patch("lifebook.llm.anthropic.Anthropic"):
            client = LLMClient(cfg)
        xml = '<｜DSML｜invoke name="search"><｜DSML｜parameter name="q">test</｜DSML｜parameter></｜DSML｜invoke>'
        client.client.messages.create.side_effect = [
            SimpleNamespace(content=[SimpleNamespace(type="text", text=xml)], stop_reason="end_turn"),
            SimpleNamespace(content=[SimpleNamespace(type="text", text="final result")]),
        ]
        result = client.agentic_call(
            system="sys",
            messages=[{"role": "user", "content": "hi"}],
            tools=[{"name": "search", "description": "d", "input_schema": {}}],
            tool_executor={},  # empty — search is recognized but has no executor
        )
        assert result == "final result"

    def test_agentic_call_text_content_with_tool_use(self):
        from lifebook.llm import LLMClient
        from lifebook.config import LLMConfig
        cfg = LLMConfig(api_key="fake", base_url="https://fake.api")
        with patch("lifebook.llm.anthropic.Anthropic"):
            client = LLMClient(cfg)
        # tool_use with accompanying text content
        client.client.messages.create.side_effect = [
            SimpleNamespace(
                content=[
                    SimpleNamespace(type="text", text="thinking..."),
                    SimpleNamespace(type="tool_use", id="t1", name="search", input={"q": "test"}),
                ],
                stop_reason="tool_use",
            ),
            SimpleNamespace(content=[SimpleNamespace(type="text", text="done")]),
        ]
        result = client.agentic_call(
            system="sys",
            messages=[{"role": "user", "content": "hi"}],
            tools=[{"name": "search", "description": "d", "input_schema": {}}],
            tool_executor={"search": MagicMock(return_value="results")},
        )
        assert result == "done"
