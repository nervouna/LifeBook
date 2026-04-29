"""Coverage tests for executor.py missing lines."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from lifebook.executor import Executor, ProcessResult


def _write_source(sources_dir: Path, filename: str, content: str = "", **meta) -> Path:
    path = sources_dir / filename
    lines = ["---"]
    for k, v in meta.items():
        lines.append(f"{k}: {v}")
    lines.append("---")
    lines.append(content)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


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
    cfg.executor.max_retries = 3
    cfg.executor.max_workers = 4
    cfg.executor.processing_delay = 0.0
    cfg.llm = MagicMock()
    cfg.tavily = MagicMock()
    cfg.fetch = MagicMock()
    cfg.vision = None
    return cfg


@pytest.fixture
def executor(mock_config):
    from lifebook.store import NoteStore
    store = NoteStore(mock_config.knowledge)
    llm = MagicMock()
    fetcher = MagicMock()
    return Executor(mock_config, store=store, llm=llm, fetcher=fetcher)


class TestProcessFileEdgeCases:
    def test_claim_exception(self, executor, mock_config):
        """Lines 68-69: claim_for_processing raises exception."""
        path = _write_source(mock_config.knowledge.sources_path, "err.md", status="inbox")
        executor.store.claim_for_processing = MagicMock(side_effect=IOError("lock failed"))
        result = executor.process_file(path)
        assert result.ok is False
        assert "read failed" in result.error

    def test_duplicate_source_url_skips(self, executor, mock_config):
        """Lines 80-90: duplicate source_url detection."""
        from lifebook.notes import read_note, write_note
        path = _write_source(
            mock_config.knowledge.sources_path, "dup.md",
            status="inbox", source="https://example.com/article",
        )
        post = read_note(path)
        post.content = "some content"
        write_note(path, post)

        executor.store.find_by_source_url = MagicMock(return_value=Path("/fake/existing.md"))
        result = executor.process_file(path)
        assert result.ok is False
        assert "duplicate" in result.skipped_reason

    def test_fetch_returns_content_with_title(self, executor, mock_config):
        """Lines 103-109: fetch ok, sets content and title."""
        from lifebook.notes import read_note, write_note
        path = _write_source(
            mock_config.knowledge.sources_path, "fetch.md",
            status="inbox", source="https://example.com",
        )
        executor.fetcher.fetch.return_value = MagicMock(
            ok=True, status="ok", content="fetched content",
            title="Fetched Title", via="tavily",
        )
        executor.llm.structured_call.return_value = {
            "title": "Fetched Title",
            "summary": "summary",
            "key_points": ["p"],
            "narrative": "narrative",
            "tags": ["资讯"],
            "category": "AI技术",
            "related_keywords": [],
            "confidence": 0.9,
        }
        result = executor.process_file(path)
        assert result.ok is True

    def test_no_content_returns_error(self, executor, mock_config):
        """Lines 111-112: no content after fetch."""
        path = _write_source(mock_config.knowledge.sources_path, "empty.md", status="inbox")
        result = executor.process_file(path)
        assert result.ok is False
        assert "no content" in result.error

    def test_aliases_set_when_title_differs_from_stem(self, executor, mock_config):
        """Lines 202-205: aliases set when slugified title != original title."""
        from lifebook.notes import read_note, write_note
        path = _write_source(mock_config.knowledge.sources_path, "alias.md", status="inbox")
        post = read_note(path)
        post.content = "Content with CJK chars"
        write_note(path, post)

        executor.llm.structured_call.return_value = {
            "title": "中文标题/特殊字符",
            "summary": "summary",
            "key_points": ["p"],
            "narrative": "narrative",
            "tags": ["资讯"],
            "category": "AI技术",
            "related_keywords": [],
            "confidence": 0.9,
        }
        result = executor.process_file(path)
        assert result.ok is True
        topic_post = read_note(result.topic_path)
        assert topic_post.get("aliases") is not None

    def test_alt_category_preserved(self, executor, mock_config):
        """Lines 191-193: alt_category propagated to topic metadata."""
        from lifebook.notes import read_note, write_note
        path = _write_source(mock_config.knowledge.sources_path, "alt.md", status="inbox")
        post = read_note(path)
        post.content = "Content"
        write_note(path, post)

        executor.llm.structured_call.return_value = {
            "title": "Test",
            "summary": "summary",
            "key_points": ["p"],
            "narrative": "narrative",
            "tags": ["资讯"],
            "category": "AI技术",
            "alt_category": "经济与产业",
            "related_keywords": [],
            "confidence": 0.7,
        }
        result = executor.process_file(path)
        assert result.ok is True
        topic_post = read_note(result.topic_path)
        assert topic_post.get("alt_category") == "经济与产业"

    def test_alt_category_invalid_ignored(self, executor, mock_config):
        """alt_category not in VALID_CATEGORIES is ignored."""
        from lifebook.notes import read_note, write_note
        path = _write_source(mock_config.knowledge.sources_path, "bad_alt.md", status="inbox")
        post = read_note(path)
        post.content = "Content"
        write_note(path, post)

        executor.llm.structured_call.return_value = {
            "title": "Test",
            "summary": "summary",
            "key_points": ["p"],
            "narrative": "narrative",
            "tags": ["资讯"],
            "category": "AI技术",
            "alt_category": "InvalidCategory",
            "related_keywords": [],
            "confidence": 0.7,
        }
        result = executor.process_file(path)
        assert result.ok is True
        topic_post = read_note(result.topic_path)
        assert topic_post.get("alt_category") is None

    def test_process_inbox_batch_limit(self, executor, mock_config):
        """Lines 220-228: batch_limit enforced."""
        for i in range(25):
            _write_source(mock_config.knowledge.sources_path, f"f{i}.md", status="inbox")
        executor.cfg.executor.batch_limit = 3
        executor.process_file = MagicMock(return_value=ProcessResult(Path("x"), True))
        results = executor.process_inbox()
        assert len(results) == 3

    def test_related_links_in_narrative(self, executor, mock_config):
        """Lines 164-169: related links injected into narrative."""
        from lifebook.notes import read_note, write_note
        path = _write_source(mock_config.knowledge.sources_path, "rel.md", status="inbox")
        post = read_note(path)
        post.content = "Content"
        write_note(path, post)

        executor.store.find_related = MagicMock(return_value=["Note A", "Note B"])
        executor.llm.structured_call.return_value = {
            "title": "Test",
            "summary": "summary",
            "key_points": ["p"],
            "narrative": "narrative body",
            "tags": ["资讯"],
            "category": "AI技术",
            "related_keywords": [],
            "confidence": 0.9,
        }
        result = executor.process_file(path)
        assert result.ok is True
        topic_post = read_note(result.topic_path)
        assert "相关笔记" in topic_post.content
        assert "[[Note-A]]" in topic_post.content or "[[Note A]]" in topic_post.content

    def test_build_extract_prompt_truncation(self, executor, mock_config):
        """Lines 252-253: content > max_chars truncated."""
        long_content = "x" * 70000
        prompt = executor._build_extract_prompt(
            title_hint="T", url="https://example.com",
            content=long_content, existing_categories=[],
        )
        assert "[...内容过长已截断...]" in prompt
        assert len(prompt) < 71000

    def test_compose_topic_body_with_source_url(self, executor):
        """Lines 269-271: source URL appended."""
        body = executor._compose_topic_body(
            summary="sum", key_points=["p1"],
            narrative="narr", source_url="https://example.com",
        )
        assert "https://example.com" in body

    def test_compose_topic_body_without_source_url(self, executor):
        """No source URL section when empty."""
        body = executor._compose_topic_body(
            summary="sum", key_points=["p1"],
            narrative="narr", source_url="",
        )
        assert "来源" not in body
