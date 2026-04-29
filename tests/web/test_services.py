"""Unit tests for web service layer."""
from __future__ import annotations

from pathlib import Path

import pytest

from lifebook.config import KnowledgeConfig
from lifebook.notes import new_post, write_note
from lifebook.web.services.note_service import NoteService
from lifebook.web.services.inbox_service import InboxService


@pytest.fixture
def kb(tmp_path: Path) -> Path:
    root = tmp_path / "kb"
    root.mkdir()
    (root / "10-sources").mkdir()
    (root / "20-topics").mkdir()
    return root


@pytest.fixture
def note_service(kb: Path) -> NoteService:
    cfg = KnowledgeConfig(root=kb)
    return NoteService(cfg)


@pytest.fixture
def inbox_service(kb: Path, tmp_path: Path) -> InboxService:
    from lifebook.config import (
        Config, LLMConfig, FeishuConfig, ExecutorConfig,
        DigestConfig, TavilyConfig, FetchConfig, LoggingConfig,
    )
    cfg = Config(
        knowledge=KnowledgeConfig(root=kb),
        llm=LLMConfig(),
        feishu=FeishuConfig(),
        executor=ExecutorConfig(),
        digest=DigestConfig(),
        tavily=TavilyConfig(),
        fetch=FetchConfig(),
        logging=LoggingConfig(),
    )
    return InboxService(cfg)


def _create_note(topics_path: Path, filename: str, **kwargs):
    title = kwargs.pop("title", filename.replace(".md", ""))
    body = kwargs.pop("body", "test content")
    post = new_post(body, title=title, **kwargs)
    write_note(topics_path / filename, post)


def _write_source(sources_dir: Path, filename: str, content: str = "", **meta) -> Path:
    path = sources_dir / filename
    lines = ["---"]
    for k, v in meta.items():
        lines.append(f"{k}: {v}")
    lines.append("---")
    lines.append(content)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# ---------- NoteService.list_notes ----------


class TestListNotes:
    def test_empty(self, note_service):
        result = note_service.list_notes()
        assert result["items"] == []
        assert result["total"] == 0

    def test_lists_all_notes(self, note_service, kb):
        td = kb / "20-topics"
        _create_note(td, "a.md", title="Note A", category="AI技术")
        _create_note(td, "b.md", title="Note B", category="半导体")
        result = note_service.list_notes()
        assert result["total"] == 2
        titles = [item["title"] for item in result["items"]]
        assert "Note A" in titles
        assert "Note B" in titles

    def test_filter_by_category(self, note_service, kb):
        td = kb / "20-topics"
        _create_note(td, "a.md", title="Note A", category="AI技术")
        _create_note(td, "b.md", title="Note B", category="半导体")
        result = note_service.list_notes(category="AI技术")
        assert result["total"] == 1
        assert result["items"][0]["title"] == "Note A"

    def test_filter_by_tag(self, note_service, kb):
        td = kb / "20-topics"
        _create_note(td, "a.md", title="Note A", tags=["deep-learning", "AI"])
        _create_note(td, "b.md", title="Note B", tags=["hardware"])
        result = note_service.list_notes(tag="deep-learning")
        assert result["total"] == 1
        assert result["items"][0]["title"] == "Note A"

    def test_pagination(self, note_service, kb):
        td = kb / "20-topics"
        for i in range(5):
            _create_note(td, f"n{i}.md", title=f"Note {i}")
        page1 = note_service.list_notes(page=1, per_page=2)
        assert len(page1["items"]) == 2
        assert page1["total"] == 5
        assert page1["page"] == 1

        page2 = note_service.list_notes(page=2, per_page=2)
        assert len(page2["items"]) == 2

        page3 = note_service.list_notes(page=3, per_page=2)
        assert len(page3["items"]) == 1

    def test_topics_dir_missing(self, note_service, kb):
        import shutil
        shutil.rmtree(kb / "20-topics")
        result = note_service.list_notes()
        assert result["items"] == []
        assert result["total"] == 0

    def test_corrupt_file_skipped(self, note_service, kb):
        td = kb / "20-topics"
        _create_note(td, "good.md", title="Good")
        bad = td / "bad.md"
        bad.write_bytes(b"\x00\x01\x80\x81\xfe\xff")
        result = note_service.list_notes()
        assert result["total"] == 1


# ---------- NoteService.get_note ----------


class TestGetNote:
    def test_valid_path(self, note_service, kb):
        td = kb / "20-topics"
        _create_note(td, "test.md", title="Test Note", body="body text")
        result = note_service.get_note("20-topics/test.md")
        assert result is not None
        assert result["title"] == "Test Note"
        assert "body text" in result["body"]

    def test_invalid_path_returns_none(self, note_service):
        result = note_service.get_note("nonexistent.md")
        assert result is None

    def test_relative_path_under_root(self, note_service, kb):
        td = kb / "20-topics" / "AI"
        td.mkdir(parents=True)
        _create_note(td, "deep.md", title="Deep Note")
        result = note_service.get_note("20-topics/AI/deep.md")
        assert result is not None
        assert result["title"] == "Deep Note"


# ---------- InboxService.list_inbox ----------


class TestListInbox:
    def test_empty(self, inbox_service, kb):
        result = inbox_service.list_inbox()
        assert result["items"] == []
        assert result["total"] == 0

    def test_lists_inbox_files(self, inbox_service, kb):
        sd = kb / "10-sources"
        _write_source(sd, "a.md", status="inbox", source_type="manual")
        _write_source(sd, "b.md", status="processed", source_type="manual")
        result = inbox_service.list_inbox()
        assert result["total"] == 1
        assert result["items"][0]["status"] == "inbox"

    def test_filter_by_status(self, inbox_service, kb):
        sd = kb / "10-sources"
        _write_source(sd, "a.md", status="inbox")
        _write_source(sd, "b.md", status="processing")
        _write_source(sd, "c.md", status="processed")
        result = inbox_service.list_inbox(status="processing")
        assert result["total"] == 1
        assert result["items"][0]["status"] == "processing"

    def test_filter_all_statuses(self, inbox_service, kb):
        sd = kb / "10-sources"
        _write_source(sd, "a.md", status="inbox")
        _write_source(sd, "b.md", status="processed")
        result = inbox_service.list_inbox(status="processed")
        assert result["total"] == 1

    def test_sources_dir_missing(self, inbox_service, kb):
        import shutil
        shutil.rmtree(kb / "10-sources")
        result = inbox_service.list_inbox()
        assert result["items"] == []
        assert result["total"] == 0

    def test_corrupt_file_skipped(self, inbox_service, kb):
        sd = kb / "10-sources"
        _write_source(sd, "good.md", status="inbox")
        bad = sd / "bad.md"
        bad.write_bytes(b"\x00\x01\x80\x81\xfe\xff")
        result = inbox_service.list_inbox()
        assert result["total"] == 1
