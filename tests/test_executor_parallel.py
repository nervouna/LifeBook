"""Tests for parallel process_inbox, fetch retry, and unified pipeline."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from lifebook.executor import Executor, ProcessResult


# ---------- fixtures ----------

@pytest.fixture
def mock_config(tmp_path):
    sources = tmp_path / "10-sources"
    sources.mkdir()
    topics = tmp_path / "20-topics"
    topics.mkdir()
    state = tmp_path / ".lifebook"
    state.mkdir()

    cfg = MagicMock()
    cfg.knowledge.root = tmp_path
    cfg.knowledge.sources_path = sources
    cfg.knowledge.topics_path = topics
    cfg.knowledge.state_path = state
    cfg.knowledge.categories = [
        "AI技术", "开发者工具", "半导体", "消费电子",
        "媒体生态", "组织与劳动", "科技监管", "经济与产业",
    ]
    cfg.executor.classify_min_confidence = 0.5
    cfg.executor.batch_limit = 20
    cfg.executor.max_workers = 2
    cfg.executor.processing_delay = 0.0
    cfg.executor.max_retries = 3

    cfg.llm = MagicMock()
    cfg.tavily = MagicMock()
    cfg.fetch = MagicMock()
    cfg.vision = None
    return cfg


def _write_source(sources_dir: Path, filename: str, content: str = "", **meta) -> Path:
    path = sources_dir / filename
    lines = ["---"]
    for k, v in meta.items():
        lines.append(f"{k}: {v}")
    lines.append("---")
    lines.append(content)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _good_extracted():
    from lifebook.config import DEFAULT_CATEGORIES
    return {
        "title": "Test Note",
        "summary": "A test summary.",
        "key_points": ["point 1"],
        "narrative": "Some narrative.",
        "tags": ["资讯", "AI技术"],
        "category": DEFAULT_CATEGORIES[0],
        "related_keywords": [],
        "confidence": 0.9,
    }


@pytest.fixture
def executor(mock_config):
    from lifebook.store import NoteStore
    store = NoteStore(mock_config.knowledge)
    llm = MagicMock()
    fetcher = MagicMock()
    return Executor(mock_config, store=store, llm=llm, fetcher=fetcher)


# ---------- parallel process_inbox ----------

class TestProcessInboxParallel:
    def test_processes_multiple_files(self, executor, mock_config):
        for i in range(3):
            path = _write_source(
                mock_config.knowledge.sources_path, f"item{i}.md",
                status="inbox",
            )
            from lifebook.notes import read_note, write_note
            post = read_note(path)
            post.content = f"content {i}"
            write_note(path, post)

        executor.llm.structured_call.return_value = _good_extracted()
        results = executor.process_inbox()
        assert len(results) == 3
        assert all(r.ok for r in results)

    def test_respects_batch_limit(self, executor, mock_config):
        mock_config.executor.batch_limit = 2
        for i in range(5):
            _write_source(
                mock_config.knowledge.sources_path, f"item{i}.md",
                status="inbox",
            )

        executor.llm.structured_call.return_value = _good_extracted()
        results = executor.process_inbox()
        assert len(results) == 2

    def test_max_workers_from_config(self, executor, mock_config):
        assert executor.cfg.executor.max_workers == 2


# ---------- fetch failure retry ----------

class TestFetchRetry:
    def test_fetch_failure_increments_retry_count(self, executor, mock_config):
        path = _write_source(
            mock_config.knowledge.sources_path, "retry1.md",
            status="inbox",
            source="https://example.com/fail",
            retry_count=0,
        )
        executor.fetcher.fetch.return_value = MagicMock(
            ok=False, status="fetch_failed", error="timeout",
        )

        result = executor.process_file(path)
        assert result.ok is False
        from lifebook.notes import read_note
        post = read_note(path)
        assert post.get("status") == "inbox"
        assert post.get("retry_count") == 1

    def test_fetch_failure_terminal_after_max_retries(self, executor, mock_config):
        path = _write_source(
            mock_config.knowledge.sources_path, "retry_max.md",
            status="inbox",
            source="https://example.com/fail",
            retry_count=3,
        )
        executor.fetcher.fetch.return_value = MagicMock(
            ok=False, status="fetch_failed", error="timeout",
        )

        result = executor.process_file(path)
        assert result.ok is False
        from lifebook.notes import read_note
        post = read_note(path)
        assert post.get("status") == "fetch_failed"

    def test_retry_failed_resets_files_to_inbox(self, executor, mock_config):
        _write_source(
            mock_config.knowledge.sources_path, "failed1.md",
            status="fetch_failed",
            source="https://example.com/a",
        )
        _write_source(
            mock_config.knowledge.sources_path, "failed2.md",
            status="fetch_failed",
            source="https://example.com/b",
        )

        count = executor.retry_failed()
        assert count == 2
        from lifebook.notes import read_note
        for name in ("failed1.md", "failed2.md"):
            post = read_note(mock_config.knowledge.sources_path / name)
            assert post.get("status") == "inbox"

    def test_retry_failed_returns_zero_when_none(self, executor, mock_config):
        count = executor.retry_failed()
        assert count == 0


# ---------- unified extraction pipeline ----------

class TestFinalizeExtraction:
    def test_finalize_creates_topic_and_marks_processed(self, executor, mock_config):
        from lifebook.notes import read_note
        path = _write_source(
            mock_config.knowledge.sources_path, "finalize.md",
            status="inbox",
        )
        post = read_note(path)
        post.content = "Some content"
        executor.store.write_note(path, post)

        extracted = _good_extracted()
        topic_path, err = executor._finalize_extraction(
            source_path=path,
            extracted=extracted,
            source_type="webclip",
            url="https://example.com",
            extra_meta={},
        )
        assert err is None
        assert topic_path.exists()
        post = read_note(path)
        assert post.get("status") == "processed"

    def test_image_path_uses_finalize(self, executor, mock_config):
        from lifebook.notes import read_note, write_note
        path = _write_source(
            mock_config.knowledge.sources_path, "img-finalize.md",
            status="inbox",
        )
        post = read_note(path)
        post.content = "content"
        write_note(path, post)

        extracted = _good_extracted()
        topic_path, err = executor._finalize_extraction(
            source_path=path,
            extracted=extracted,
            source_type="image",
            url="",
            extra_meta={},
        )
        assert err is None
        assert topic_path.exists()
