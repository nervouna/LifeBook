"""Tests for lifebook.writer."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import frontmatter
import pytest

from lifebook.config import (
    Config, KnowledgeConfig, LLMConfig, FeishuConfig,
    ExecutorConfig, DigestConfig, TavilyConfig, FetchConfig, LoggingConfig,
)
from lifebook.notes import new_post, write_note, read_note
from lifebook.writer import (
    Writer, STAGE_CONCEPT, STAGE_FRAMEWORK, STAGE_CONTENT, STAGE_REVIEW,
)


# ── helpers ──────────────────────────────────────────────────────────


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
    "concept_text": "这是核心概念文本。",
}

FRAMEWORK_RESULT = {
    "frameworks": [
        {
            "name": "方案A",
            "outline": [
                {"heading": "引言", "point": "引入话题"},
                {"heading": "论证", "point": "展开论证"},
            ],
        },
        {
            "name": "方案B",
            "outline": [
                {"heading": "背景", "point": "交代背景"},
            ],
        },
    ]
}

CONTENT_TEXT = """\
## 引言

这是引言段落。

## 论证

这是论证段落。

---

- 数据来源：2023年
- 推理：因果推断
"""

BACKFILL_RESULT = {
    "should_backfill": True,
    "items": [
        {
            "action": "create",
            "topic_title": "新知识点",
            "reason": "新事实",
            "content": "新内容片段",
        },
        {
            "action": "update",
            "topic_title": "已有主题",
            "reason": "补充数据",
            "content": "补充内容",
        },
    ],
}


# ── 1. Static helpers ────────────────────────────────────────────────


class TestExtractSection:
    body = (
        "## 核心概念\n\n概念内容\n\n## 框架\n\n框架内容\n\n## 正文\n\n正文内容\n"
    )

    def test_extract_without_keep_header(self):
        result = Writer._extract_section(self.body, "核心概念")
        assert "概念内容" in result
        assert "## 核心概念" not in result

    def test_extract_with_keep_header(self):
        result = Writer._extract_section(self.body, "核心概念", keep_header=True)
        assert result.startswith("## 核心概念")
        assert "概念内容" in result
        # Should NOT include next section
        assert "框架内容" not in result

    def test_missing_heading(self):
        assert Writer._extract_section(self.body, "不存在") == ""

    def test_last_section(self):
        result = Writer._extract_section(self.body, "正文")
        assert "正文内容" in result

    def test_multiple_sections_isolation(self):
        r1 = Writer._extract_section(self.body, "框架")
        assert "框架内容" in r1
        assert "概念内容" not in r1
        assert "正文内容" not in r1


class TestSplitChecklist:
    def test_separator(self):
        text = "正文内容\n---\n清单内容"
        body, checklist = Writer._split_checklist(text)
        assert body == "正文内容"
        assert checklist == "清单内容"

    def test_heading(self):
        text = "正文内容\n\n## 自检清单\n\n- item1\n- item2"
        body, checklist = Writer._split_checklist(text)
        assert "正文内容" in body
        assert "item1" in checklist

    def test_no_checklist(self):
        text = "纯正文没有清单"
        body, checklist = Writer._split_checklist(text)
        assert body == text
        assert checklist == ""

# ── 2. State machine ────────────────────────────────────────────────


class TestStateMachine:
    def test_start_creates_draft(self, tmp_path):
        w, llm, cfg = make_writer(tmp_path)
        llm.structured_call.return_value = CONCEPT_RESULT
        result = w.start("我想写关于测试的文章")
        assert w.active
        assert w.stage == STAGE_CONCEPT
        assert "核心概念" in result
        assert w.draft_path.exists()

    def test_start_rejects_if_draft_exists(self, tmp_path):
        w, llm, cfg = make_writer(tmp_path)
        llm.structured_call.return_value = CONCEPT_RESULT
        w.start("idea1")
        result = w.start("idea2")
        assert "已有一篇草稿" in result

    def test_handle_message_no_draft(self, tmp_path):
        w, llm, cfg = make_writer(tmp_path)
        result = w.handle_message("hello")
        assert "没有进行中" in result

    def test_handle_message_concept_advances_to_framework(self, tmp_path):
        w, llm, cfg = make_writer(tmp_path)
        llm.structured_call.return_value = CONCEPT_RESULT
        w.start("idea")
        llm.structured_call.return_value = FRAMEWORK_RESULT
        result = w.handle_message("确认")
        assert w.stage == STAGE_FRAMEWORK
        assert "方案" in result

    def test_handle_message_framework_advances_to_content(self, tmp_path):
        w, llm, cfg = make_writer(tmp_path)
        # concept
        llm.structured_call.return_value = CONCEPT_RESULT
        w.start("idea")
        # framework
        llm.structured_call.return_value = FRAMEWORK_RESULT
        w.handle_message("确认")
        # content
        llm.text_call.return_value = CONTENT_TEXT
        result = w.handle_message("选方案1")
        assert w.stage == STAGE_CONTENT
        assert "引言" in result

    def test_handle_message_content_goes_to_review(self, tmp_path):
        w, llm, cfg = make_writer(tmp_path)
        llm.structured_call.return_value = CONCEPT_RESULT
        w.start("idea")
        llm.structured_call.return_value = FRAMEWORK_RESULT
        w.handle_message("确认")
        llm.text_call.return_value = CONTENT_TEXT
        w.handle_message("选方案1")
        # discuss
        llm.agentic_call.return_value = "好的，我已修改了引言部分。"
        w.handle_message("修改一下引言")
        assert w.stage == STAGE_REVIEW


# ── 4. Publish flow ──────────────────────────────────────────────────


class TestPublish:
    def _setup_content_stage(self, tmp_path):
        w, llm, cfg = make_writer(tmp_path)
        llm.structured_call.return_value = CONCEPT_RESULT
        w.start("idea")
        llm.structured_call.return_value = FRAMEWORK_RESULT
        w.handle_message("确认")
        llm.text_call.return_value = CONTENT_TEXT
        w.handle_message("选方案1")
        return w, llm, cfg

    def test_publish_creates_file_and_deletes_draft(self, tmp_path):
        w, llm, cfg = self._setup_content_stage(tmp_path)
        # backfill returns nothing
        llm.structured_call.return_value = {"should_backfill": False, "items": []}
        result = w.publish()
        assert "已发布" in result
        assert not w.draft_path.exists()
        # Check published file exists
        pub_files = list(cfg.knowledge.publish_path.glob("*.md"))
        # Filter out draft.md (shouldn't exist)
        pub_files = [f for f in pub_files if f.name != "draft.md"]
        assert len(pub_files) == 1

    def test_publish_rejects_concept_stage(self, tmp_path):
        w, llm, cfg = make_writer(tmp_path)
        llm.structured_call.return_value = CONCEPT_RESULT
        w.start("idea")
        result = w.publish()
        assert "还不能发布" in result

    def test_publish_rejects_framework_stage(self, tmp_path):
        w, llm, cfg = make_writer(tmp_path)
        llm.structured_call.return_value = CONCEPT_RESULT
        w.start("idea")
        llm.structured_call.return_value = FRAMEWORK_RESULT
        w.handle_message("确认")
        result = w.publish()
        assert "还不能发布" in result

    def test_publish_no_active_draft(self, tmp_path):
        w, llm, cfg = make_writer(tmp_path)
        result = w.publish()
        assert "没有进行中" in result


# ── 5. Backfill ──────────────────────────────────────────────────────


class TestBackfill:
    def test_backfill_create(self, tmp_path):
        w, llm, cfg = make_writer(tmp_path)
        path = w._backfill_create("新主题", "新内容", "来源文章")
        assert path.exists()
        post = read_note(path)
        assert post.get("title") == "新主题"
        assert "新内容" in post.content
        assert post.get("backfilled_from") == "来源文章"

    def test_backfill_update_existing(self, tmp_path):
        w, llm, cfg = make_writer(tmp_path)
        td = cfg.knowledge.topics_path
        orig = new_post("原始内容\n", title="已有主题")
        write_note(td / "existing.md", orig)

        ok = w._backfill_update("已有主题", "补充内容", "来源文章")
        assert ok is True
        post = read_note(td / "existing.md")
        assert "补充内容" in post.content
        assert "来源文章" in post.content

    def test_backfill_update_not_found(self, tmp_path):
        w, llm, cfg = make_writer(tmp_path)
        ok = w._backfill_update("不存在的主题", "内容", "来源")
        assert ok is False

    def test_backfill_update_no_topics_dir(self, tmp_path):
        w, llm, cfg = make_writer(tmp_path)
        import shutil
        shutil.rmtree(cfg.knowledge.topics_path)
        ok = w._backfill_update("任何主题", "内容", "来源")
        assert ok is False


# ── 6. Thread safety ──────────────────────────────────────────────


class TestThreadSafety:
    def test_concurrent_handle_message_no_corruption(self, tmp_path):
        """Two threads calling handle_message concurrently should not corrupt the draft."""
        import threading

        w, llm, cfg = make_writer(tmp_path)
        llm.structured_call.return_value = CONCEPT_RESULT
        w.start("idea")
        llm.structured_call.return_value = FRAMEWORK_RESULT
        w.handle_message("确认")
        llm.text_call.return_value = CONTENT_TEXT
        w.handle_message("选方案1")

        # Now at content stage — two threads discuss simultaneously
        llm.agentic_call.side_effect = [
            "回复A: 已修改引言",
            "回复B: 已修改论证",
        ]

        errors = []

        def discuss(msg):
            try:
                w.handle_message(msg)
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=discuss, args=("修改引言",))
        t2 = threading.Thread(target=discuss, args=("修改论证",))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert not errors, f"Concurrent access raised: {errors}"
        # Draft should still be valid
        assert w.active
        assert w.stage in (STAGE_CONTENT, STAGE_REVIEW)

    def test_concurrent_start_and_publish(self, tmp_path):
        """start() and publish() running concurrently should not cause file corruption."""
        import threading

        w, llm, cfg = make_writer(tmp_path)
        llm.structured_call.return_value = CONCEPT_RESULT
        w.start("idea")
        llm.structured_call.return_value = FRAMEWORK_RESULT
        w.handle_message("确认")
        llm.text_call.return_value = CONTENT_TEXT
        w.handle_message("选方案1")
        llm.structured_call.return_value = {"should_backfill": False, "items": []}

        errors = []

        def do_publish():
            try:
                w.publish()
            except Exception as e:
                errors.append(e)

        def do_discuss():
            try:
                w.handle_message("修改引言")
            except Exception as e:
                errors.append(e)

        llm.agentic_call.return_value = "已修改"
        t1 = threading.Thread(target=do_publish)
        t2 = threading.Thread(target=do_discuss)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert not errors, f"Concurrent access raised: {errors}"

    def test_lock_exists_on_writer(self, tmp_path):
        """Writer must have a threading.Lock for serializing public API calls."""
        import threading
        w, llm, cfg = make_writer(tmp_path)
        assert hasattr(w, "_lock"), "Writer must have a _lock attribute"
        assert isinstance(w._lock, type(threading.Lock())), "Writer._lock must be a threading.Lock"
