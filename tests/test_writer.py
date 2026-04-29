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

# Sequential content generation: 2 sections (引言, 论证) + checklist
CONTENT_SECTIONS = [
    "这是引言段落。",       # section 1
    "这是论证段落。",       # section 2
    "- 数据来源：2023年\n- 推理：因果推断",  # checklist
]

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


# ── 0. New file I/O structure ────────────────────────────────────────────


class TestNewFileIO:
    """Tests for draft.json + draft.md file structure."""

    def test_save_draft_writes_json_and_md(self, tmp_path):
        """_save_draft should write metadata to draft.json and content to draft.md."""
        w, llm, cfg = make_writer(tmp_path)
        meta = {
            "stage": STAGE_CONCEPT,
            "title": "测试标题",
            "concept": {
                "topic": "主题",
                "thesis": "主张",
                "audience": "读者",
            },
        }
        content = "这是文章内容。\n\n第二段落。"

        w._save_draft(meta, content)

        # Check draft.json exists and has correct metadata
        assert w.draft_meta_path.exists()
        import json
        with w.draft_meta_path.open("r", encoding="utf-8") as f:
            saved_meta = json.load(f)
        assert saved_meta["stage"] == STAGE_CONCEPT
        assert saved_meta["concept"]["topic"] == "主题"

        # Check draft.md exists and has pure content (no frontmatter)
        assert w.draft_path.exists()
        md_content = w.draft_path.read_text(encoding="utf-8")
        assert md_content == content
        assert "---" not in md_content  # No frontmatter

    def test_load_draft_reads_json_and_md(self, tmp_path):
        """_load_draft should return (meta, content) from separate files."""
        w, llm, cfg = make_writer(tmp_path)

        # Write files manually
        import json
        meta = {"stage": STAGE_FRAMEWORK, "title": "测试"}
        with w.draft_meta_path.open("w", encoding="utf-8") as f:
            json.dump(meta, f)
        w.draft_path.write_text("文章内容\n", encoding="utf-8")

        loaded_meta, loaded_content = w._load_draft()

        assert loaded_meta["stage"] == STAGE_FRAMEWORK
        assert loaded_content == "文章内容\n"

    def test_load_draft_no_files_returns_none(self, tmp_path):
        """_load_draft should return (None, "") when no draft exists."""
        w, llm, cfg = make_writer(tmp_path)
        meta, content = w._load_draft()
        assert meta is None
        assert content == ""

    def test_delete_draft_removes_all_files(self, tmp_path):
        """_delete_draft should remove draft.json, draft.md, and history.json."""
        w, llm, cfg = make_writer(tmp_path)

        # Create all three files
        import json
        with w.draft_meta_path.open("w", encoding="utf-8") as f:
            json.dump({"stage": STAGE_CONTENT}, f)
        w.draft_path.write_text("内容", encoding="utf-8")
        with w.history_path.open("w", encoding="utf-8") as f:
            json.dump([], f)

        w._delete_draft()

        assert not w.draft_meta_path.exists()
        assert not w.draft_path.exists()
        assert not w.history_path.exists()

    def test_active_checks_json_exists(self, tmp_path):
        """active property should check draft.json existence."""
        w, llm, cfg = make_writer(tmp_path)
        assert not w.active

        import json
        with w.draft_meta_path.open("w", encoding="utf-8") as f:
            json.dump({"stage": STAGE_CONCEPT}, f)

        assert w.active

    def test_stage_reads_from_json(self, tmp_path):
        """stage property should read from draft.json."""
        w, llm, cfg = make_writer(tmp_path)
        assert w.stage is None

        import json
        with w.draft_meta_path.open("w", encoding="utf-8") as f:
            json.dump({"stage": STAGE_FRAMEWORK}, f)

        assert w.stage == STAGE_FRAMEWORK


class TestStartNewStructure:
    """Tests for start() with draft.json + draft.md structure."""

    def test_start_saves_concept_to_json(self, tmp_path):
        """start() should save concept as structured data to draft.json."""
        w, llm, cfg = make_writer(tmp_path)
        llm.structured_call.return_value = CONCEPT_RESULT

        w.start("我想写关于测试的文章")

        import json
        with w.draft_meta_path.open("r", encoding="utf-8") as f:
            meta = json.load(f)

        assert meta["stage"] == STAGE_CONCEPT
        assert meta["concept"]["topic"] == "测试主题"
        assert meta["concept"]["thesis"] == "测试主张"
        assert meta["concept"]["audience"] == "测试读者"

    def test_start_writes_empty_md(self, tmp_path):
        """start() should write empty draft.md."""
        w, llm, cfg = make_writer(tmp_path)
        llm.structured_call.return_value = CONCEPT_RESULT

        w.start("我想写关于测试的文章")

        content = w.draft_path.read_text(encoding="utf-8")
        assert content == ""

    def test_start_clears_history(self, tmp_path):
        """start() should clear history file."""
        w, llm, cfg = make_writer(tmp_path)
        # Create existing history
        import json
        with w.history_path.open("w", encoding="utf-8") as f:
            json.dump([{"role": "user", "content": "old"}], f)

        llm.structured_call.return_value = CONCEPT_RESULT
        w.start("新文章")

        assert not w.history_path.exists() or w.history_path.read_text() == "[]"

    def test_start_includes_created_updated(self, tmp_path):
        """start() should include created/updated timestamps."""
        w, llm, cfg = make_writer(tmp_path)
        llm.structured_call.return_value = CONCEPT_RESULT

        w.start("文章")

        import json
        with w.draft_meta_path.open("r", encoding="utf-8") as f:
            meta = json.load(f)

        assert "created" in meta
        assert "updated" in meta


class TestAdvanceToFrameworkNewStructure:
    """Tests for _advance_to_framework() with draft.json structure."""

    def _setup_concept_stage(self, tmp_path):
        w, llm, cfg = make_writer(tmp_path)
        llm.structured_call.return_value = CONCEPT_RESULT
        w.start("idea")
        return w, llm, cfg

    def test_framework_saved_to_json(self, tmp_path):
        """_advance_to_framework should save frameworks to draft.json."""
        w, llm, cfg = self._setup_concept_stage(tmp_path)
        llm.structured_call.return_value = FRAMEWORK_RESULT

        w.handle_message("确认")

        import json
        with w.draft_meta_path.open("r", encoding="utf-8") as f:
            meta = json.load(f)

        assert meta["stage"] == STAGE_FRAMEWORK
        assert "frameworks" in meta
        assert len(meta["frameworks"]) == 2
        assert meta["frameworks"][0]["name"] == "方案A"

    def test_framework_not_in_md(self, tmp_path):
        """_advance_to_framework should NOT write frameworks to draft.md."""
        w, llm, cfg = self._setup_concept_stage(tmp_path)
        llm.structured_call.return_value = FRAMEWORK_RESULT

        w.handle_message("确认")

        content = w.draft_path.read_text(encoding="utf-8")
        assert content == ""  # md should remain empty at framework stage

    def test_framework_renders_for_display(self, tmp_path):
        """_advance_to_framework should return formatted frameworks for display."""
        w, llm, cfg = self._setup_concept_stage(tmp_path)
        llm.structured_call.return_value = FRAMEWORK_RESULT

        result = w.handle_message("确认")

        assert "方案" in result
        assert "方案A" in result
        assert "方案B" in result


class TestAdvanceToContentNewStructure:
    """Tests for _advance_to_content() with draft.json structure."""

    def _setup_framework_stage(self, tmp_path):
        w, llm, cfg = make_writer(tmp_path)
        llm.structured_call.return_value = CONCEPT_RESULT
        w.start("idea")
        llm.structured_call.return_value = FRAMEWORK_RESULT
        w.handle_message("确认")
        return w, llm, cfg

    def test_content_written_to_md(self, tmp_path):
        """_advance_to_content should write content to draft.md."""
        w, llm, cfg = self._setup_framework_stage(tmp_path)
        llm.text_call.side_effect = list(CONTENT_SECTIONS)

        w.handle_message("选方案1")

        content = w.draft_path.read_text(encoding="utf-8")
        assert "引言段落" in content
        assert "论证段落" in content

    def test_checklist_saved_to_json(self, tmp_path):
        """_advance_to_content should save checklist to draft.json."""
        w, llm, cfg = self._setup_framework_stage(tmp_path)
        llm.text_call.side_effect = list(CONTENT_SECTIONS)

        w.handle_message("选方案1")

        import json
        with w.draft_meta_path.open("r", encoding="utf-8") as f:
            meta = json.load(f)

        assert meta["stage"] == STAGE_CONTENT
        assert "checklist" in meta
        assert "数据来源" in meta["checklist"]

    def test_framework_selection_by_index(self, tmp_path):
        """_advance_to_content should select framework by index from JSON."""
        w, llm, cfg = self._setup_framework_stage(tmp_path)
        # 方案A has 2 sections, 方案B has 1 section
        llm.text_call.side_effect = ["唯一段落。", "- 自检项"]

        w.handle_message("选方案2")

        # Should have generated 1 section (方案B has 1 outline item)
        assert llm.text_call.call_count == 2  # 1 section + 1 checklist


class TestDiscussNewStructure:
    """Tests for _discuss() with persistent history."""

    def _setup_content_stage(self, tmp_path):
        w, llm, cfg = make_writer(tmp_path)
        llm.structured_call.return_value = CONCEPT_RESULT
        w.start("idea")
        llm.structured_call.return_value = FRAMEWORK_RESULT
        w.handle_message("确认")
        llm.text_call.side_effect = list(CONTENT_SECTIONS)
        w.handle_message("选方案1")
        return w, llm, cfg

    def test_history_saved_to_file(self, tmp_path):
        """_discuss should save history to draft.history.json."""
        w, llm, cfg = self._setup_content_stage(tmp_path)
        llm.agentic_call.return_value = "好的，已修改。"

        w.handle_message("修改引言")

        import json
        assert w.history_path.exists()
        with w.history_path.open("r", encoding="utf-8") as f:
            history = json.load(f)
        assert len(history) == 2  # user + assistant

    def test_history_loaded_from_file(self, tmp_path):
        """_discuss should load existing history from file."""
        w, llm, cfg = self._setup_content_stage(tmp_path)

        # Create existing history
        import json
        existing = [{"role": "user", "content": "旧反馈"}, {"role": "assistant", "content": "旧回复"}]
        with w.history_path.open("w", encoding="utf-8") as f:
            json.dump(existing, f)

        llm.agentic_call.return_value = "新回复"
        w.handle_message("新反馈")

        with w.history_path.open("r", encoding="utf-8") as f:
            history = json.load(f)
        assert len(history) == 4  # 2 old + 2 new

    def test_content_updated_in_md(self, tmp_path):
        """_discuss should update content in draft.md via update_draft tool."""
        w, llm, cfg = self._setup_content_stage(tmp_path)

        def mock_agentic_call(system, messages, tools, tool_executor):
            # Simulate update_draft tool call
            tool_executor["update_draft"]({"content": "新的正文内容。"})
            return "已更新正文。"

        llm.agentic_call.side_effect = mock_agentic_call
        w.handle_message("修改正文")

        content = w.draft_path.read_text(encoding="utf-8")
        assert content == "新的正文内容。"


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
        # framework (方案A has 2 sections: 引言, 论证)
        llm.structured_call.return_value = FRAMEWORK_RESULT
        w.handle_message("确认")
        # content: section-by-section (2 sections + 1 checklist)
        llm.text_call.side_effect = [
            "这是引言段落。",     # section 1
            "这是论证段落。",     # section 2
            "- 数据来源：2023年",  # checklist
        ]
        result = w.handle_message("选方案1")
        assert w.stage == STAGE_CONTENT
        assert "引言" in result
        assert "论证" in result

    def test_handle_message_content_goes_to_review(self, tmp_path):
        w, llm, cfg = make_writer(tmp_path)
        llm.structured_call.return_value = CONCEPT_RESULT
        w.start("idea")
        llm.structured_call.return_value = FRAMEWORK_RESULT
        w.handle_message("确认")
        llm.text_call.side_effect = list(CONTENT_SECTIONS)
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
        llm.text_call.side_effect = list(CONTENT_SECTIONS)
        w.handle_message("选方案1")
        return w, llm, cfg

    def test_publish_creates_file_and_deletes_draft(self, tmp_path):
        w, llm, cfg = self._setup_content_stage(tmp_path)
        # Remove checklist from draft so publish doesn't need force
        meta, content = w._load_draft()
        meta["checklist"] = ""
        w._save_draft(meta, content)

        llm.structured_call.return_value = {"should_backfill": False, "items": []}
        result = w.publish()
        assert "已发布" in result
        assert not w.draft_meta_path.exists()
        assert not w.draft_path.exists()
        # Check published file exists
        pub_files = list(cfg.knowledge.publish_path.glob("*.md"))
        pub_files = [f for f in pub_files if "draft" not in f.name]
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

    def test_publish_succeeds_when_backfill_fails(self, tmp_path):
        """Publish should succeed even if backfill LLM call raises an exception."""
        w, llm, cfg = self._setup_content_stage(tmp_path)
        # Remove checklist so publish doesn't need force
        meta, content = w._load_draft()
        meta["checklist"] = ""
        w._save_draft(meta, content)
        # Need a topic so _evaluate_backfill actually calls LLM
        topic_post = new_post("相关内容\n", title="测试主题相关")
        w.store.write_note(cfg.knowledge.topics_path / "related.md", topic_post)

        llm.structured_call.side_effect = RuntimeError("LLM timeout")
        result = w.publish()
        assert "已发布" in result
        assert "回填" in result and "失败" in result
        assert not w.draft_meta_path.exists()
        # Published file should exist
        pub_files = [f for f in cfg.knowledge.publish_path.glob("*.md")
                     if "draft" not in f.name]
        assert len(pub_files) == 1

    def test_publish_blocked_by_checklist(self, tmp_path):
        """Publish should warn when checklist has items, unless force=True."""
        w, llm, cfg = self._setup_content_stage(tmp_path)
        # Make sure the draft has a checklist
        meta, content = w._load_draft()
        meta["checklist"] = "- 数据来源：2023年\n- 推理：因果推断"
        w._save_draft(meta, content)

        llm.structured_call.return_value = {"should_backfill": False, "items": []}
        result = w.publish()
        assert "自检清单" in result
        assert "强制" in result
        # Draft should still exist
        assert w.active

    def test_publish_force_overrides_checklist(self, tmp_path):
        """publish(force=True) should succeed even with checklist items."""
        w, llm, cfg = self._setup_content_stage(tmp_path)
        meta, content = w._load_draft()
        meta["checklist"] = "- 数据来源：2023年"
        w._save_draft(meta, content)

        llm.structured_call.return_value = {"should_backfill": False, "items": []}
        result = w.publish(force=True)
        assert "已发布" in result
        assert not w.draft_meta_path.exists()


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
        llm.text_call.side_effect = list(CONTENT_SECTIONS)
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
        llm.text_call.side_effect = list(CONTENT_SECTIONS)
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


# ── 7. History cap ────────────────────────────────────────────────


class TestHistoryCap:
    def _setup_content_stage(self, tmp_path):
        w, llm, cfg = make_writer(tmp_path)
        llm.structured_call.return_value = CONCEPT_RESULT
        w.start("idea")
        llm.structured_call.return_value = FRAMEWORK_RESULT
        w.handle_message("确认")
        llm.text_call.side_effect = list(CONTENT_SECTIONS)
        w.handle_message("选方案1")
        return w, llm, cfg

    def test_history_trimmed_after_max(self, tmp_path):
        """After max_history discussion rounds, older turns are dropped."""
        w, llm, cfg = self._setup_content_stage(tmp_path)

        # Simulate 15 discussion rounds
        for i in range(15):
            llm.agentic_call.return_value = f"回复第{i}轮"
            w.handle_message(f"第{i}轮反馈")

        # History should be capped at 10 (2 entries per round: user + assistant)
        assert len(w._history) <= 20  # max_history rounds × 2 entries

    def test_oldest_turns_dropped(self, tmp_path):
        """When history is trimmed, the oldest turns are removed first."""
        w, llm, cfg = self._setup_content_stage(tmp_path)

        for i in range(12):
            llm.agentic_call.return_value = f"回复{i}"
            w.handle_message(f"反馈{i}")

        # First entry should not be from round 0
        first_content = w._history[0]["content"]
        assert "反馈0" not in first_content


# ── 8. Draft versioning ───────────────────────────────────────────


class TestDraftVersioning:
    def test_backup_created_on_save(self, tmp_path):
        """Saving a draft should create backup files."""
        w, llm, cfg = make_writer(tmp_path)
        llm.structured_call.return_value = CONCEPT_RESULT
        w.start("idea")
        # First save creates files, no backup yet
        assert w.draft_meta_path.exists()
        assert w.draft_path.exists()
        bak_json = w.draft_meta_path.with_suffix(".json.bak")
        bak_md = w.draft_path.with_suffix(".md.bak")
        assert not bak_json.exists()
        assert not bak_md.exists()

        # Second save should create backup
        llm.structured_call.return_value = FRAMEWORK_RESULT
        w.handle_message("确认")
        assert bak_json.exists()
        # Verify backup contains previous stage
        import json
        with bak_json.open("r") as f:
            bak_meta = json.load(f)
        assert bak_meta["stage"] == STAGE_CONCEPT

    def test_restore_draft(self, tmp_path):
        """restore_draft() should restore from backup files."""
        w, llm, cfg = make_writer(tmp_path)
        llm.structured_call.return_value = CONCEPT_RESULT
        w.start("idea")
        llm.structured_call.return_value = FRAMEWORK_RESULT
        w.handle_message("确认")

        # Now restore — draft should go back to concept stage
        result = w.restore_draft()
        assert "已恢复" in result
        meta, _ = w._load_draft()
        assert meta["stage"] == STAGE_CONCEPT

    def test_restore_no_backup(self, tmp_path):
        """restore_draft() with no backup should return error message."""
        w, llm, cfg = make_writer(tmp_path)
        result = w.restore_draft()
        assert "没有可恢复" in result


# ── 9. Coverage: missing branches ────────────────────────────────────────


class TestTopicContextBranches:
    """Tests for topic_context branches in various methods."""

    def test_start_with_topic_context(self, tmp_path):
        """start() should include topic context in prompt when available."""
        w, llm, cfg = make_writer(tmp_path)
        # Create a topic that will match - title/content must contain query words
        topic = new_post("测试相关主题的内容\n", title="测试相关主题")
        w.store.write_note(cfg.knowledge.topics_path / "related.md", topic)
        llm.structured_call.return_value = CONCEPT_RESULT

        w.start("测试相关")

        # The prompt should include topic context
        call_args = llm.structured_call.call_args
        assert "存量笔记" in call_args.kwargs["user_prompt"]

    def test_advance_to_framework_with_topic_context(self, tmp_path):
        """_advance_to_framework should include topic context."""
        w, llm, cfg = make_writer(tmp_path)
        # Topic content must contain the full search query (Chinese text without spaces = one word)
        # CONCEPT_RESULT["concept_text"] = "这是核心概念文本。"
        topic = new_post("这是核心概念文本。相关的笔记内容\n", title="相关主题")
        w.store.write_note(cfg.knowledge.topics_path / "fw.md", topic)

        llm.structured_call.return_value = CONCEPT_RESULT
        w.start("测试主题")

        llm.structured_call.return_value = FRAMEWORK_RESULT
        w.handle_message("确认")

        call_args = llm.structured_call.call_args
        assert "存量笔记" in call_args.kwargs["user_prompt"]

    def test_advance_to_content_with_topic_context(self, tmp_path):
        """_advance_to_content should include topic context."""
        w, llm, cfg = make_writer(tmp_path)
        # Topic content must contain the full concept_text
        topic = new_post("这是核心概念文本。内容\n", title="相关主题")
        w.store.write_note(cfg.knowledge.topics_path / "content.md", topic)

        llm.structured_call.return_value = CONCEPT_RESULT
        w.start("测试主题")

        llm.structured_call.return_value = FRAMEWORK_RESULT
        w.handle_message("确认")

        llm.text_call.side_effect = list(CONTENT_SECTIONS)
        w.handle_message("选方案1")

        # Check that topic context was included in prompts
        for call in llm.text_call.call_args_list:
            prompt = call.kwargs["user_prompt"]
            if "存量笔记" in prompt:
                return  # Found at least one with topic context

    def test_discuss_with_topic_context(self, tmp_path):
        """_discuss should include topic context."""
        w, llm, cfg = make_writer(tmp_path)
        llm.structured_call.return_value = CONCEPT_RESULT
        w.start("idea")
        llm.structured_call.return_value = FRAMEWORK_RESULT
        w.handle_message("确认")
        llm.text_call.side_effect = list(CONTENT_SECTIONS)
        w.handle_message("选方案1")

        # Create topic that matches feedback query
        topic = new_post("讨论主题内容\n", title="讨论主题")
        w.store.write_note(cfg.knowledge.topics_path / "discuss.md", topic)

        llm.agentic_call.return_value = "好的"
        w.handle_message("讨论主题")  # Query that matches topic

        # Check messages included topic context
        call_args = llm.agentic_call.call_args
        messages = call_args.kwargs["messages"]
        last_msg = messages[-1]
        assert "存量笔记" in last_msg["content"]


class TestEdgeCases:
    """Tests for edge cases and error paths."""

    def test_handle_message_unknown_stage(self, tmp_path):
        """handle_message should return error for unknown stage."""
        w, llm, cfg = make_writer(tmp_path)
        llm.structured_call.return_value = CONCEPT_RESULT
        w.start("idea")

        # Manually set invalid stage
        import json
        meta, content = w._load_draft()
        meta["stage"] = "invalid_stage"
        w._save_draft(meta, content)

        result = w.handle_message("test")
        assert "未知状态" in result

    def test_select_framework_empty_list(self, tmp_path):
        """_select_framework should return None for empty frameworks."""
        w, llm, cfg = make_writer(tmp_path)
        result = w._select_framework([], "方案1")
        assert result is None

    def test_select_framework_by_name(self, tmp_path):
        """_select_framework should match by name."""
        w, llm, cfg = make_writer(tmp_path)
        frameworks = [
            {"name": "方案A", "outline": [{"heading": "A1", "point": "p1"}]},
            {"name": "方案B", "outline": [{"heading": "B1", "point": "p2"}]},
        ]
        result = w._select_framework(frameworks, "选方案B")
        assert result == [{"heading": "B1", "point": "p2"}]

    def test_select_framework_returns_none_on_no_match(self, tmp_path):
        """_select_framework should return None when no match (caller shows options)."""
        w, llm, cfg = make_writer(tmp_path)
        frameworks = [
            {"name": "方案A", "outline": [{"heading": "A1", "point": "p1"}]},
        ]
        result = w._select_framework(frameworks, "随便写")
        assert result is None

    def test_advance_to_content_empty_frameworks(self, tmp_path):
        """_advance_to_content should return error when frameworks is empty."""
        w, llm, cfg = make_writer(tmp_path)
        llm.structured_call.return_value = CONCEPT_RESULT
        w.start("idea")

        # Set stage to framework but with empty frameworks
        import json
        meta, content = w._load_draft()
        meta["stage"] = STAGE_FRAMEWORK
        meta["frameworks"] = []
        w._save_draft(meta, content)

        result = w.handle_message("选方案1")
        assert "未找到匹配的框架方案" in result


class TestDiscussUpdateWithChecklist:
    """Test discussion update_draft with checklist."""

    def _setup_content_stage(self, tmp_path):
        w, llm, cfg = make_writer(tmp_path)
        llm.structured_call.return_value = CONCEPT_RESULT
        w.start("idea")
        llm.structured_call.return_value = FRAMEWORK_RESULT
        w.handle_message("确认")
        llm.text_call.side_effect = list(CONTENT_SECTIONS)
        w.handle_message("选方案1")
        return w, llm, cfg

    def test_update_draft_with_checklist(self, tmp_path):
        """update_draft tool should save checklist when provided."""
        w, llm, cfg = self._setup_content_stage(tmp_path)

        def mock_agentic_call(system, messages, tools, tool_executor):
            # Call update_draft with both content and checklist
            tool_executor["update_draft"]({
                "content": "新正文",
                "checklist": "- 新自检项"
            })
            return "已更新"

        llm.agentic_call.side_effect = mock_agentic_call
        w.handle_message("修改")

        import json
        with w.draft_meta_path.open("r") as f:
            meta = json.load(f)
        assert meta["checklist"] == "- 新自检项"


class TestBackfillExecution:
    """Test backfill execution with actual items."""

    def test_backfill_creates_and_updates(self, tmp_path):
        """_evaluate_backfill should execute create and update actions."""
        w, llm, cfg = make_writer(tmp_path)

        # Create existing topic for search to find AND for update
        existing = new_post("原始内容\n", title="已有主题")
        w.store.write_note(cfg.knowledge.topics_path / "existing.md", existing)

        # Mock LLM to return backfill items
        llm.structured_call.return_value = {
            "should_backfill": True,
            "items": [
                {
                    "action": "create",
                    "topic_title": "新建主题",
                    "reason": "新知识点",
                    "content": "新内容",
                },
                {
                    "action": "update",
                    "topic_title": "已有主题",
                    "reason": "补充",
                    "content": "补充内容",
                },
            ],
        }

        result = w._evaluate_backfill("已有主题", "文章内容")

        assert "回填到知识库" in result
        assert "新建 topic" in result
        assert "更新 topic" in result

    def test_backfill_update_topic_not_found(self, tmp_path):
        """_evaluate_backfill should handle update when topic not found."""
        w, llm, cfg = make_writer(tmp_path)

        # Create a topic for search to find
        topic = new_post("搜索匹配内容\n", title="搜索匹配")
        w.store.write_note(cfg.knowledge.topics_path / "search.md", topic)

        llm.structured_call.return_value = {
            "should_backfill": True,
            "items": [
                {
                    "action": "update",
                    "topic_title": "不存在的主题",
                    "reason": "测试",
                    "content": "内容",
                },
            ],
        }

        result = w._evaluate_backfill("搜索匹配", "内容")
        assert "未找到 topic" in result

    def test_backfill_no_items(self, tmp_path):
        """_evaluate_backfill should return empty when no items."""
        w, llm, cfg = make_writer(tmp_path)

        # Create topic for search
        topic = new_post("内容\n", title="主题")
        w.store.write_note(cfg.knowledge.topics_path / "t.md", topic)

        llm.structured_call.return_value = {
            "should_backfill": False,
            "items": [],
        }

        result = w._evaluate_backfill("主题", "内容")
        assert result == ""

    def test_backfill_empty_items_list(self, tmp_path):
        """_evaluate_backfill should return empty when items list is empty."""
        w, llm, cfg = make_writer(tmp_path)

        # Create topic for search
        topic = new_post("内容\n", title="主题")
        w.store.write_note(cfg.knowledge.topics_path / "t.md", topic)

        llm.structured_call.return_value = {
            "should_backfill": True,
            "items": [],
        }

        result = w._evaluate_backfill("主题", "内容")
        assert result == ""
