"""Unit tests for executor.py."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from lifebook.executor import Executor, ProcessResult


# ---------- fixtures ----------

@pytest.fixture
def mock_config(tmp_path):
    """Create a mock Config with tmp_path directory structure."""
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
    cfg.executor.classify_min_confidence = 0.5
    cfg.executor.batch_limit = 20

    cfg.llm = MagicMock()
    cfg.tavily = MagicMock()
    cfg.fetch = MagicMock()
    return cfg


def _write_source(sources_dir: Path, filename: str, content: str = "", **meta) -> Path:
    """Write a minimal inbox source file."""
    path = sources_dir / filename
    lines = ["---"]
    for k, v in meta.items():
        lines.append(f"{k}: {v}")
    lines.append("---")
    lines.append(content)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def executor(mock_config):
    """Create an Executor with mocked LLM, Fetcher, and NoteStore."""
    with patch("lifebook.executor.LLMClient"), patch("lifebook.executor.Fetcher"):
        from lifebook.store import NoteStore
        store = NoteStore(mock_config.knowledge)
        ex = Executor(mock_config, store=store)
        ex.llm = MagicMock()
        ex.fetcher = MagicMock()
        return ex


# ---------- scan_inbox ----------

class TestScanInbox:
    def test_finds_inbox_files(self, executor, mock_config):
        _write_source(mock_config.knowledge.sources_path, "a.md", status="inbox")
        _write_source(mock_config.knowledge.sources_path, "b.md", status="processed")
        _write_source(mock_config.knowledge.sources_path, "c.md", status="inbox")

        result = executor.scan_inbox()
        assert len(result) == 2
        assert all(p.name.endswith(".md") for p in result)

    def test_empty_sources_dir(self, executor, mock_config):
        result = executor.scan_inbox()
        assert result == []

    def test_missing_sources_dir(self, executor, mock_config):
        import shutil
        shutil.rmtree(mock_config.knowledge.sources_path)
        result = executor.scan_inbox()
        assert result == []


# ---------- recover_stale ----------

class TestRecoverStale:
    def test_recovers_stale_processing(self, executor, mock_config):
        _write_source(
            mock_config.knowledge.sources_path, "stale.md",
            status="processing",
            processing_at="2020-01-01T00:00:00+08:00",
        )

        result = executor.recover_stale(timeout_minutes=10)
        assert len(result) == 1
        assert result[0][0].name == "stale.md"

    def test_ignores_fresh_processing(self, executor, mock_config):
        from lifebook.notes import now_iso
        _write_source(
            mock_config.knowledge.sources_path, "fresh.md",
            status="processing",
            processing_at=now_iso(),
        )

        result = executor.recover_stale(timeout_minutes=10)
        assert result == []

    def test_dry_run_does_not_modify(self, executor, mock_config):
        path = _write_source(
            mock_config.knowledge.sources_path, "stale.md",
            status="processing",
            processing_at="2020-01-01T00:00:00+08:00",
        )

        executor.recover_stale(timeout_minutes=10, dry_run=True)

        from lifebook.notes import read_note
        post = read_note(path)
        assert post.get("status") == "processing"


# ---------- process_file ----------

class TestProcessFile:
    def test_skips_non_inbox(self, executor, mock_config):
        path = _write_source(
            mock_config.knowledge.sources_path, "done.md",
            status="processed",
        )

        result = executor.process_file(path)
        assert result.ok is False
        assert "already processed" in result.skipped_reason

    def test_fetch_failure_marks_skipped(self, executor, mock_config):
        path = _write_source(
            mock_config.knowledge.sources_path, "url.md",
            status="inbox",
            source="https://example.com/bad",
        )
        executor.fetcher.fetch.return_value = MagicMock(
            ok=False, status="fetch_failed", error="timeout",
        )

        result = executor.process_file(path)
        assert result.ok is False
        assert "fetch_failed" in result.skipped_reason

    def test_low_confidence_skips(self, executor, mock_config):
        path = _write_source(
            mock_config.knowledge.sources_path, "low.md",
            status="inbox",
        )
        from lifebook.notes import read_note, write_note
        post = read_note(path)
        post.content = "Some content here"
        write_note(path, post)

        executor.llm.structured_call.return_value = {
            "title": "Test",
            "summary": "summary",
            "key_points": ["point"],
            "narrative": "narrative text",
            "tags": ["tag1", "tag2"],
            "category": "AI技术",
            "related_keywords": [],
            "confidence": 0.2,
        }

        result = executor.process_file(path)
        assert result.ok is False
        assert "low confidence" in result.skipped_reason

    def test_successful_processing(self, executor, mock_config):
        from lifebook.notes import read_note, write_note
        path = _write_source(
            mock_config.knowledge.sources_path, "good.md",
            status="inbox",
        )
        post = read_note(path)
        post.content = "Some real content about AI"
        write_note(path, post)

        executor.llm.structured_call.return_value = {
            "title": "AI Overview",
            "summary": "An overview of AI",
            "key_points": ["point 1", "point 2"],
            "narrative": "Detailed narrative about AI.",
            "tags": ["资讯", "AI-tech"],
            "category": "AI技术",
            "related_keywords": [],
            "confidence": 0.9,
        }

        result = executor.process_file(path)
        assert result.ok is True
        assert result.topic_path is not None
        assert result.topic_path.exists()

        updated_post = read_note(path)
        assert updated_post.get("status") == "processed"

    def test_llm_failure_returns_error(self, executor, mock_config):
        from lifebook.notes import read_note, write_note
        path = _write_source(
            mock_config.knowledge.sources_path, "fail.md",
            status="inbox",
        )
        post = read_note(path)
        post.content = "Content"
        write_note(path, post)

        executor.llm.structured_call.side_effect = RuntimeError("API error")

        result = executor.process_file(path)
        assert result.ok is False
        assert "LLM failed" in result.error

    def test_extra_frontmatter_preserved_in_prompt_and_topic(self, executor, mock_config):
        from lifebook.notes import read_note, write_note
        path = _write_source(
            mock_config.knowledge.sources_path, "trending.md",
            status="inbox",
            source_type="trending",
            source="https://github.com/owner/repo",
            trending_source="github",
            star_velocity="50.0",
        )
        post = read_note(path)
        post.content = "A trending project about AI agents"
        write_note(path, post)

        executor.llm.structured_call.return_value = {
            "title": "AI Agent Project",
            "summary": "An AI agent framework",
            "key_points": ["fast growing"],
            "narrative": "Details about the project.",
            "tags": ["资讯", "AI-Agent"],
            "category": "AI技术",
            "related_keywords": [],
            "confidence": 0.9,
        }

        # Capture the user_prompt passed to structured_call
        captured = {}
        original_call = executor.llm.structured_call
        def capture_call(**kwargs):
            captured.update(kwargs)
            return original_call.return_value
        executor.llm.structured_call.side_effect = capture_call

        result = executor.process_file(path)
        assert result.ok is True

        # Verify extra metadata appears in the LLM prompt
        prompt = captured["user_prompt"]
        assert "trending_source" in prompt
        assert "github" in prompt
        assert "star_velocity" in prompt

        # Verify extra metadata carried into topic note frontmatter
        topic_post = read_note(result.topic_path)
        assert topic_post.get("source_trending_source") == "github"
        assert str(topic_post.get("source_star_velocity")) == "50.0"
