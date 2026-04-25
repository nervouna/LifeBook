"""Tests for web schemas."""
from __future__ import annotations

from lifebook.web.schemas import (
    NoteListItem,
    NoteDetail,
    InboxItem,
    SearchResultItem,
    WriterStatus,
    WriterChatRequest,
    StatsResponse,
)


def test_note_list_item():
    item = NoteListItem(path="20-topics/AI技术/Test.md", title="Test", category="AI技术", tags=["tag1"], created="2026-01-01", status="active")
    assert item.title == "Test"


def test_note_detail():
    detail = NoteDetail(path="20-topics/AI技术/Test.md", title="Test", category="AI技术", tags=[], created="2026-01-01", body="content", metadata={})
    assert detail.body == "content"


def test_inbox_item():
    item = InboxItem(path="10-sources/test.md", title="Test", status="inbox", source_type="manual", created="2026-01-01")
    assert item.status == "inbox"


def test_search_result_item():
    item = SearchResultItem(path="20-topics/AI技术/Test.md", title="Test", score=0.95, preview="text...")
    assert item.score == 0.95


def test_writer_status():
    status = WriterStatus(active=True, stage="concept", title="My Article")
    assert status.active is True


def test_writer_chat_request():
    req = WriterChatRequest(message="hello")
    assert req.message == "hello"


def test_stats_response():
    stats = StatsResponse(topic_count=10, inbox_count=3, categories=["AI技术"])
    assert stats.topic_count == 10
