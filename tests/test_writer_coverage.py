"""Coverage tests for writer.py missing lines."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from lifebook.config import (
    Config, KnowledgeConfig, LLMConfig, FeishuConfig,
    ExecutorConfig, DigestConfig, TavilyConfig, FetchConfig, LoggingConfig,
)
from lifebook.notes import new_post, now_iso, write_note
from lifebook.writer import Writer, STAGE_CONCEPT, STAGE_CONTENT, STAGE_FRAMEWORK, STAGE_REVIEW


def make_cfg(tmp_path: Path) -> Config:
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "20-topics").mkdir()
    (kb / "99-publish").mkdir()
    return Config(
        knowledge=KnowledgeConfig(root=kb),
        llm=LLMConfig(),
        feishu=FeishuConfig(),
        executor=ExecutorConfig(),
        digest=DigestConfig(),
        tavily=TavilyConfig(),
        fetch=FetchConfig(),
        logging=LoggingConfig(),
    )


def make_writer(tmp_path: Path) -> tuple[Writer, MagicMock, Config]:
    cfg = make_cfg(tmp_path)
    llm = MagicMock()
    w = Writer(cfg, llm)
    return w, llm, cfg


CONCEPT_RESULT = {
    "topic": "测试主题",
    "thesis": "测试主张",
    "audience": "测试读者",
    "concept_text": "概念文本。",
}

FRAMEWORK_RESULT = {
    "frameworks": [
        {
            "name": "方案A",
            "outline": [
                {"heading": "引言", "point": "引入"},
                {"heading": "论证", "point": "展开"},
            ],
        },
    ]
}


class TestWriterEdgeCases:
    def test_unknown_stage_returns_message(self, tmp_path):
        w, llm, cfg = make_writer(tmp_path)
        meta = {"stage": "unknown_stage", "title": "T", "created": now_iso(), "updated": now_iso()}
        w.draft_meta_path.parent.mkdir(parents=True, exist_ok=True)
        w.draft_meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        w.draft_path.write_text("body", encoding="utf-8")
        result = w.handle_message("hello")
        assert "未知状态" in result

    def test_advance_to_content_fallback_no_outline(self, tmp_path):
        w, llm, cfg = make_writer(tmp_path)
        llm.structured_call.return_value = CONCEPT_RESULT
        w.start("idea")
        llm.structured_call.return_value = FRAMEWORK_RESULT
        w.handle_message("确认")
        result = w.handle_message("随便写没有框架的内容")
        # No match → error with options, stage stays at framework
        assert w.stage == STAGE_FRAMEWORK
        assert "未找到匹配" in result
        assert "方案" in result

    def test_evaluate_backfill_no_context(self, tmp_path):
        w, llm, cfg = make_writer(tmp_path)
        result = w._evaluate_backfill("Title", "Content")
        assert result == ""

    def test_evaluate_backfill_should_not_backfill(self, tmp_path):
        w, llm, cfg = make_writer(tmp_path)
        td = cfg.knowledge.topics_path
        td.mkdir(parents=True, exist_ok=True)
        write_note(td / "t.md", new_post("body", title="Test"))
        llm.structured_call.return_value = {"should_backfill": False, "items": []}
        result = w._evaluate_backfill("Test", "Content")
        assert result == ""

    def test_delete_draft_no_file(self, tmp_path):
        w, llm, cfg = make_writer(tmp_path)
        w._delete_draft()  # should not raise

    def test_discuss_history_trimmed(self, tmp_path):
        w, llm, cfg = make_writer(tmp_path)
        llm.structured_call.return_value = CONCEPT_RESULT
        w.start("idea")
        llm.structured_call.return_value = FRAMEWORK_RESULT
        w.handle_message("确认")
        llm.text_call.side_effect = ["引言段落", "论证段落", "- checklist"]
        w.handle_message("选方案1")
        for i in range(25):
            llm.agentic_call.return_value = f"回复{i}"
            w.handle_message(f"反馈{i}")
        from lifebook.writer import MAX_HISTORY
        assert len(w._history) <= MAX_HISTORY

    def test_discuss_draft_updated_flag(self, tmp_path):
        w, llm, cfg = make_writer(tmp_path)
        llm.structured_call.return_value = CONCEPT_RESULT
        w.start("idea")
        llm.structured_call.return_value = FRAMEWORK_RESULT
        w.handle_message("确认")
        llm.text_call.side_effect = ["引言段落", "论证段落", "- checklist"]
        w.handle_message("选方案1")

        def fake_agentic(system, messages, tools, tool_executor, **kwargs):
            tool_executor["update_draft"]({"content": "new content", "checklist": "- item"})
            return "已更新"
        llm.agentic_call.side_effect = fake_agentic
        w.handle_message("修改")
        assert w.stage == STAGE_REVIEW

    def test_backfill_update_not_found_in_publish(self, tmp_path):
        """Lines 482: backfill update topic not found — returns '未找到'."""
        w, llm, cfg = make_writer(tmp_path)
        llm.structured_call.return_value = CONCEPT_RESULT
        w.start("idea")
        llm.structured_call.return_value = FRAMEWORK_RESULT
        w.handle_message("确认")
        llm.text_call.side_effect = ["引言段落", "论证段落", "- checklist"]
        w.handle_message("选方案1")
        # Remove checklist from draft.json
        meta, content = w._load_draft()
        meta["checklist"] = ""
        w._save_draft(meta, content)
        # Create a topic so _evaluate_backfill gets non-empty topic_context
        # The topic title must match the publish title "测试主题" for search to find it.
        # Also invalidate the store cache so Writer picks up the new topic.
        td = cfg.knowledge.topics_path
        td.mkdir(parents=True, exist_ok=True)
        write_note(td / "test_topic.md", new_post("related content", title="测试主题"))
        w.store._invalidate_topic_cache()
        # Backfill wants to update a topic that doesn't exist
        llm.structured_call.return_value = {
            "should_backfill": True,
            "items": [{"action": "update", "topic_title": "NonExistentTopic", "reason": "r", "content": "c"}],
        }
        result = w.publish()
        assert "已发布" in result
        assert "未找到" in result

    def test_topic_context_in_start(self, tmp_path):
        w, llm, cfg = make_writer(tmp_path)
        td = cfg.knowledge.topics_path
        td.mkdir(parents=True, exist_ok=True)
        write_note(td / "existing.md", new_post("body about AI", title="AI发展"))
        llm.structured_call.return_value = CONCEPT_RESULT
        w.start("AI发展")
        call_kwargs = llm.structured_call.call_args
        prompt = call_kwargs.kwargs.get("user_prompt", call_kwargs.args[0] if call_kwargs.args else "")
        assert "用户的写作想法" in prompt

    def test_advance_to_framework_with_topic_context(self, tmp_path):
        """Lines 226: topic_context in framework prompt."""
        w, llm, cfg = make_writer(tmp_path)
        llm.structured_call.return_value = CONCEPT_RESULT
        w.start("idea about 测试主题")
        w.store.search_topics_formatted = MagicMock(return_value="### 旧笔记\n一些内容")
        llm.structured_call.return_value = FRAMEWORK_RESULT
        result = w.handle_message("确认")
        assert "方案" in result

    def test_advance_to_content_no_outline(self, tmp_path):
        """Empty outline → stays at framework stage with rejection message."""
        w, llm, cfg = make_writer(tmp_path)
        llm.structured_call.return_value = CONCEPT_RESULT
        w.start("idea about 测试主题")
        w.store.search_topics_formatted = MagicMock(return_value="### 旧笔记\n一些内容")
        llm.structured_call.return_value = {
            "frameworks": [{"name": "A", "outline": []}]
        }
        w.handle_message("确认")
        result = w.handle_message("随便写")
        assert w.stage == STAGE_FRAMEWORK
        assert "未找到" in result

    def test_section_gen_with_topic_context(self, tmp_path):
        """Lines 303: topic_context in per-section generation."""
        w, llm, cfg = make_writer(tmp_path)
        llm.structured_call.return_value = CONCEPT_RESULT
        w.start("idea about 测试主题")
        llm.structured_call.return_value = FRAMEWORK_RESULT
        w.handle_message("确认")
        w.store.search_topics_formatted = MagicMock(return_value="### 旧笔记\n一些内容")
        llm.text_call.side_effect = ["section 1 content", "section 2 content", "- checklist"]
        result = w.handle_message("选方案1")
        assert w.stage == STAGE_CONTENT

    def test_discuss_with_topic_context(self, tmp_path):
        """Lines 374: topic_context in discuss mode."""
        w, llm, cfg = make_writer(tmp_path)
        llm.structured_call.return_value = CONCEPT_RESULT
        w.start("idea about 测试主题")
        llm.structured_call.return_value = FRAMEWORK_RESULT
        w.handle_message("确认")
        llm.text_call.side_effect = ["intro", "body", "- check"]
        w.handle_message("选方案1")
        w.store.search_topics_formatted = MagicMock(return_value="### 旧笔记\n一些内容")
        llm.agentic_call.return_value = "讨论回复"
        result = w.handle_message("某个问题")
        assert "讨论回复" in result
