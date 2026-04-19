"""Unit tests for store.py (NoteStore)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from lifebook.config import KnowledgeConfig
from lifebook.notes import new_post, write_note
from lifebook.store import NoteStore, TopicHit


@pytest.fixture
def store(tmp_path):
    """Create a NoteStore with tmp_path directories."""
    sources = tmp_path / "10-sources"
    sources.mkdir()
    topics = tmp_path / "20-topics"
    topics.mkdir()
    state = tmp_path / ".lifebook"
    state.mkdir()
    cfg = KnowledgeConfig(root=tmp_path)
    return NoteStore(cfg)


def _create_topic(topics_dir: Path, filename: str, **kwargs):
    title = kwargs.pop("title", filename.replace(".md", ""))
    body = kwargs.pop("body", "默认内容")
    post = new_post(body, title=title, **kwargs)
    write_note(topics_dir / filename, post)


def _write_source(sources_dir: Path, filename: str, content: str = "", **meta) -> Path:
    path = sources_dir / filename
    lines = ["---"]
    for k, v in meta.items():
        lines.append(f"{k}: {v}")
    lines.append("---")
    lines.append(content)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# ---------- scan_inbox ----------

class TestScanInbox:
    def test_finds_inbox_files(self, store):
        _write_source(store.cfg.sources_path, "a.md", status="inbox")
        _write_source(store.cfg.sources_path, "b.md", status="processed")
        _write_source(store.cfg.sources_path, "c.md", status="inbox")
        assert len(store.scan_inbox()) == 2

    def test_empty_sources_dir(self, store):
        assert store.scan_inbox() == []

    def test_missing_sources_dir(self, store):
        import shutil
        shutil.rmtree(store.cfg.sources_path)
        assert store.scan_inbox() == []


# ---------- claim_for_processing ----------

class TestClaimForProcessing:
    def test_claims_inbox_file(self, store):
        path = _write_source(store.cfg.sources_path, "a.md", status="inbox")
        claimed, post = store.claim_for_processing(path)
        assert claimed is True
        assert post.get("status") == "processing"
        assert post.get("processing_at") is not None

    def test_rejects_non_inbox(self, store):
        path = _write_source(store.cfg.sources_path, "a.md", status="processed")
        claimed, post = store.claim_for_processing(path)
        assert claimed is False
        assert post.get("status") == "processed"


# ---------- recover_stale ----------

class TestRecoverStale:
    def test_recovers_stale_processing(self, store):
        _write_source(
            store.cfg.sources_path, "stale.md",
            status="processing",
            processing_at="2020-01-01T00:00:00+08:00",
        )
        result = store.recover_stale(timeout_minutes=10)
        assert len(result) == 1

    def test_ignores_fresh_processing(self, store):
        from lifebook.notes import now_iso
        _write_source(
            store.cfg.sources_path, "fresh.md",
            status="processing",
            processing_at=now_iso(),
        )
        assert store.recover_stale(timeout_minutes=10) == []


# ---------- existing_categories ----------

class TestExistingCategories:
    def test_lists_subdirectories(self, store):
        (store.cfg.topics_path / "AI技术").mkdir()
        (store.cfg.topics_path / "游戏").mkdir()
        cats = store.existing_categories()
        assert "AI技术" in cats
        assert "游戏" in cats

    def test_ignores_hidden_dirs(self, store):
        (store.cfg.topics_path / ".hidden").mkdir()
        (store.cfg.topics_path / "公开").mkdir()
        cats = store.existing_categories()
        assert ".hidden" not in cats
        assert "公开" in cats

    def test_empty_when_no_topics_dir(self, store):
        import shutil
        shutil.rmtree(store.cfg.topics_path)
        assert store.existing_categories() == []


# ---------- find_related ----------

class TestFindRelated:
    def test_finds_matching_notes(self, store):
        td = store.cfg.topics_path
        cat_dir = td / "AI技术"
        cat_dir.mkdir(parents=True, exist_ok=True)
        note = cat_dir / "test.md"
        note.write_text("""---
title: Deep Learning Intro
tags:
  - deep-learning
  - AI
related_keywords:
  - neural-network
---

Body text.
""", encoding="utf-8")

        result = store.find_related(["deep-learning", "neural-network"])
        assert "Deep Learning Intro" in result

    def test_no_keywords_returns_empty(self, store):
        assert store.find_related([]) == []

    def test_no_match_returns_empty(self, store):
        assert store.find_related(["nonexistent-term-xyz"]) == []


# ---------- find_by_title ----------

class TestFindByTitle:
    def test_finds_by_exact_title(self, store):
        _create_topic(store.cfg.topics_path, "test.md", title="My Note")
        result = store.find_by_title("My Note")
        assert result is not None
        assert result.name == "test.md"

    def test_finds_by_slug(self, store):
        _create_topic(store.cfg.topics_path, "my-note.md", title="My Note")
        result = store.find_by_title("My Note")
        assert result is not None

    def test_returns_none_when_not_found(self, store):
        assert store.find_by_title("Nonexistent") is None


# ---------- topic_count ----------

class TestTopicCount:
    def test_counts_notes(self, store):
        _create_topic(store.cfg.topics_path / "AI技术", "a.md", title="A")
        _create_topic(store.cfg.topics_path / "游戏", "b.md", title="B")
        assert store.topic_count() == 2

    def test_zero_when_empty(self, store):
        assert store.topic_count() == 0


# ---------- search_topics ----------

class TestSearchTopics:
    def test_category_match_scores_highest(self, store):
        td = store.cfg.topics_path
        _create_topic(td, "a.md", title="无关标题A", category="投资", body="无关内容")
        _create_topic(td, "b.md", title="无关标题B", tags=["投资"], body="无关内容")
        _create_topic(td, "c.md", title="投资指南", body="无关内容")
        _create_topic(td, "d.md", title="无关标题D", body="投资是重要的事情")

        hits = store.search_topics("投资")
        assert len(hits) > 0
        # Category match (3.0) should score highest
        assert hits[0].title == "无关标题A"

    def test_max_notes_limit(self, store):
        td = store.cfg.topics_path
        for i in range(10):
            _create_topic(td, f"n{i}.md", title=f"投资话题{i}", body="投资内容")
        hits = store.search_topics("投资", max_notes=3)
        assert len(hits) == 3

    def test_empty_on_no_match(self, store):
        td = store.cfg.topics_path
        _create_topic(td, "a.md", title="完全无关", body="完全无关内容")
        hits = store.search_topics("量子物理")
        assert hits == []

    def test_empty_when_no_topics_dir(self, store):
        import shutil
        shutil.rmtree(store.cfg.topics_path)
        assert store.search_topics("anything") == []

    def test_formatted_output(self, store):
        td = store.cfg.topics_path
        _create_topic(td, "a.md", title="投资指南", body="投资内容")
        result = store.search_topics_formatted("投资")
        assert "### 投资指南" in result

    def test_formatted_empty(self, store):
        assert store.search_topics_formatted("量子物理") == ""
