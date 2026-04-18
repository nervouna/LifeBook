"""End-to-end tests for the Writer writing flow with mocked LLM but real file I/O."""
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
        llm=LLMConfig(), feishu=FeishuConfig(), executor=ExecutorConfig(),
        digest=DigestConfig(), tavily=TavilyConfig(), fetch=FetchConfig(), logging=LoggingConfig(),
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

DISCUSS_RESPONSE_1 = """\
## 引言

修改后的引言段落，增加了背景信息。

## 论证

修改后的论证段落，补充了数据。

---

- 数据来源：2024年更新
"""

DISCUSS_RESPONSE_2 = """\
## 引言

再次修改的引言，更加精炼。

## 论证

最终版本的论证段落。

---

- 数据来源：最终版本
"""

BACKFILL_NONE = {"should_backfill": False, "items": []}

BACKFILL_CREATE = {
    "should_backfill": True,
    "items": [
        {
            "action": "create",
            "topic_title": "新知识点",
            "reason": "文章引用了新事实",
            "content": "这是需要回填的新内容",
        }
    ],
}

BACKFILL_UPDATE = {
    "should_backfill": True,
    "items": [
        {
            "action": "update",
            "topic_title": "已有主题",
            "reason": "补充了新数据",
            "content": "补充的新数据内容",
        }
    ],
}


# ── Full flow e2e test ───────────────────────────────────────────────


class TestFullWritingFlow:
    """Exercise the complete writing flow: start → concept → framework → content → discuss × 2 → publish."""

    def test_full_flow(self, tmp_path):
        w, llm, cfg = make_writer(tmp_path)

        # We need topics for backfill context to trigger _evaluate_backfill's LLM call
        topics_dir = cfg.knowledge.topics_path
        topic_post = new_post("相关内容关于测试主题\n", title="测试主题相关")
        write_note(topics_dir / "related.md", topic_post)

        # Set up LLM mock side_effects
        # structured_call sequence: concept, framework, backfill
        llm.structured_call.side_effect = [
            CONCEPT_RESULT,      # start() -> concept
            FRAMEWORK_RESULT,    # handle_message("确认") -> framework
            BACKFILL_NONE,       # publish() -> backfill eval
        ]
        # text_call sequence: content, discuss1, discuss2
        llm.text_call.side_effect = [
            CONTENT_TEXT,        # handle_message("选方案1") -> content
            DISCUSS_RESPONSE_1,  # handle_message("修改引言") -> discuss round 1
            DISCUSS_RESPONSE_2,  # handle_message("再改论证") -> discuss round 2
        ]

        # Step 1: /write (start) → concept stage
        result = w.start("我想写关于测试的文章")
        assert w.active
        assert w.stage == STAGE_CONCEPT
        assert "核心概念" in result
        assert "测试主题" in result
        assert w.draft_path.exists()
        draft = read_note(w.draft_path)
        assert draft.get("stage") == STAGE_CONCEPT
        assert "测试主题" in draft.content

        # Step 2: User confirms concept → framework stage
        result = w.handle_message("确认，概念很好")
        assert w.stage == STAGE_FRAMEWORK
        assert "方案" in result
        draft = read_note(w.draft_path)
        assert draft.get("stage") == STAGE_FRAMEWORK
        assert "框架" in draft.content

        # Step 3: User picks framework → content stage, draft has 正文
        result = w.handle_message("选方案1")
        assert w.stage == STAGE_CONTENT
        assert "引言" in result
        draft = read_note(w.draft_path)
        assert draft.get("stage") == STAGE_CONTENT
        assert "正文" in draft.content

        # Step 4a: Discussion round 1
        result = w.handle_message("请修改引言部分")
        assert w.stage == STAGE_REVIEW
        assert "修改后的引言" in result
        draft = read_note(w.draft_path)
        assert draft.get("stage") == STAGE_REVIEW

        # Step 4b: Discussion round 2
        result = w.handle_message("再改一下论证部分")
        assert w.stage == STAGE_REVIEW
        assert "最终版本" in result
        draft = read_note(w.draft_path)
        assert "再次修改" in draft.content or "最终版本" in draft.content

        # Step 5: /publish → file in 99-publish/, draft deleted
        result = w.publish()
        assert "已发布" in result
        assert not w.draft_path.exists()

        # Verify published file
        pub_files = [f for f in cfg.knowledge.publish_path.glob("*.md") if f.name != "draft.md"]
        assert len(pub_files) == 1
        pub_post = read_note(pub_files[0])
        assert pub_post.get("title") == "测试主题"
        assert pub_post.get("status") == "published"


# ── Edge case tests ──────────────────────────────────────────────────


class TestEdgeCases:
    def test_start_rejected_when_draft_exists(self, tmp_path):
        """Start a new /write while draft exists → rejected."""
        w, llm, cfg = make_writer(tmp_path)
        llm.structured_call.return_value = CONCEPT_RESULT
        w.start("idea1")
        assert w.active

        result = w.start("idea2")
        assert "已有一篇草稿" in result
        # Original draft still intact
        assert w.stage == STAGE_CONCEPT

    def test_publish_rejected_at_concept_stage(self, tmp_path):
        """/publish at concept stage → rejected."""
        w, llm, cfg = make_writer(tmp_path)
        llm.structured_call.return_value = CONCEPT_RESULT
        w.start("idea")
        assert w.stage == STAGE_CONCEPT

        result = w.publish()
        assert "还不能发布" in result
        assert w.active  # draft still exists

    def test_publish_rejected_at_framework_stage(self, tmp_path):
        """/publish at framework stage → rejected."""
        w, llm, cfg = make_writer(tmp_path)
        llm.structured_call.side_effect = [CONCEPT_RESULT, FRAMEWORK_RESULT]
        w.start("idea")
        w.handle_message("确认")
        assert w.stage == STAGE_FRAMEWORK

        result = w.publish()
        assert "还不能发布" in result
        assert w.active

    def test_restart_recovery(self, tmp_path):
        """Create a draft.md manually, verify Writer picks it up."""
        cfg = make_cfg(tmp_path)
        llm = MagicMock()

        # Manually create a draft at content stage
        draft_path = cfg.knowledge.publish_path / "draft.md"
        post = new_post(
            "## 核心概念\n\n概念内容\n\n## 框架\n\n框架内容\n\n## 正文\n\n正文内容\n",
            title="手动草稿",
            stage=STAGE_CONTENT,
            created="2024-01-01T00:00:00",
            updated="2024-01-01T00:00:00",
        )
        write_note(draft_path, post)

        # Create new Writer instance (simulates restart)
        w = Writer(cfg, llm)
        assert w.active is True
        assert w.stage == STAGE_CONTENT

    def test_restart_recovery_review_stage(self, tmp_path):
        """Recovery at review stage."""
        cfg = make_cfg(tmp_path)
        llm = MagicMock()
        draft_path = cfg.knowledge.publish_path / "draft.md"
        post = new_post("## 正文\n\n内容\n", title="草稿", stage=STAGE_REVIEW)
        write_note(draft_path, post)

        w = Writer(cfg, llm)
        assert w.active is True
        assert w.stage == STAGE_REVIEW


class TestBackfillE2E:
    def test_backfill_creates_new_topic(self, tmp_path):
        """Backfill creates new topic file when LLM says should_backfill=True with create."""
        w, llm, cfg = make_writer(tmp_path)
        topics_dir = cfg.knowledge.topics_path

        # Need a related topic so _evaluate_backfill has context and calls LLM
        topic_post = new_post("相关内容\n", title="测试主题相关")
        write_note(topics_dir / "related.md", topic_post)

        # Set up full flow to content stage
        llm.structured_call.side_effect = [
            CONCEPT_RESULT,
            FRAMEWORK_RESULT,
            BACKFILL_CREATE,  # backfill eval returns create
        ]
        llm.text_call.return_value = CONTENT_TEXT

        w.start("idea")
        w.handle_message("确认")
        w.handle_message("选方案1")

        result = w.publish()
        assert "已发布" in result
        assert "新建 topic" in result
        assert "新知识点" in result

        # Verify topic file was created
        topic_files = list(topics_dir.glob("*.md"))
        titles = []
        for f in topic_files:
            p = read_note(f)
            titles.append(p.get("title"))
        assert "新知识点" in titles

    def test_backfill_updates_existing_topic(self, tmp_path):
        """Backfill updates existing topic when LLM says update."""
        w, llm, cfg = make_writer(tmp_path)
        topics_dir = cfg.knowledge.topics_path

        # Create existing topic to update (title must match backfill target)
        existing_post = new_post("原始内容\n", title="已有主题")
        write_note(topics_dir / "existing.md", existing_post)
        # Also need a topic matching the article title so _evaluate_backfill finds context
        related_post = new_post("测试主题相关内容\n", title="测试主题参考")
        write_note(topics_dir / "related.md", related_post)

        llm.structured_call.side_effect = [
            CONCEPT_RESULT,
            FRAMEWORK_RESULT,
            BACKFILL_UPDATE,  # backfill eval returns update
        ]
        llm.text_call.return_value = CONTENT_TEXT

        w.start("idea")
        w.handle_message("确认")
        w.handle_message("选方案1")

        result = w.publish()
        assert "已发布" in result
        assert "更新 topic" in result
        assert "已有主题" in result

        # Verify existing topic was updated
        updated = read_note(topics_dir / "existing.md")
        assert "补充的新数据内容" in updated.content
        assert "原始内容" in updated.content
