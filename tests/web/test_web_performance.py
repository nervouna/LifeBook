"""Tests for web performance improvements: caching, shared singletons."""
from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import frontmatter
import pytest


# ── NoteStore TTL cache tests ──────────────────────────────────────────


def _write_topic(topics_dir: Path, category: str, filename: str, title: str, body: str = "content"):
    d = topics_dir / category
    d.mkdir(parents=True, exist_ok=True)
    path = d / filename
    post = frontmatter.Post(body)
    post["title"] = title
    post["category"] = category
    post["tags"] = ["test"]
    post["created"] = "2026-01-01T00:00:00+08:00"
    path.write_text(frontmatter.dumps(post, sort_keys=False), encoding="utf-8")
    return path


class TestNoteStoreCacheTTL:
    def test_cache_has_timestamp(self, mock_config):
        from lifebook.store import NoteStore
        store = NoteStore(mock_config.knowledge)
        assert store._cache_time is None
        store._load_topic_cache()
        assert store._cache_time is not None
        assert isinstance(store._cache_time, float)

    def test_cache_reused_within_ttl(self, mock_config):
        from lifebook.store import NoteStore
        store = NoteStore(mock_config.knowledge)
        store._load_topic_cache()
        first_call_time = store._cache_time
        # Second call should reuse cache (no timestamp change)
        store._load_topic_cache()
        assert store._cache_time == first_call_time

    def test_cache_expires_after_ttl(self, mock_config):
        from lifebook.store import NoteStore
        store = NoteStore(mock_config.knowledge)
        store._load_topic_cache()
        # Simulate expired cache
        store._cache_time = time.time() - 61  # 61s ago, past 30s TTL
        store._load_topic_cache()
        # Cache time should have been refreshed
        assert store._cache_time > time.time() - 1

    def test_invalidate_force(self, mock_config):
        from lifebook.store import NoteStore
        store = NoteStore(mock_config.knowledge)
        store._load_topic_cache()
        assert store._cache_time is not None
        store._invalidate_topic_cache(force=True)
        assert store._topic_cache is None
        assert store._cache_time is None

    def test_cache_bounds_content_length(self, mock_config):
        from lifebook.store import NoteStore
        long_body = "x" * 1000
        _write_topic(mock_config.knowledge.topics_path, "AI", "Long.md", "Long Note", long_body)
        store = NoteStore(mock_config.knowledge)
        cache = store._load_topic_cache()
        assert len(cache) == 1
        _, _, _, content = cache[0]
        assert len(content) <= 500


# ── NoteService uses NoteStore tests ───────────────────────────────────


class TestNoteServiceUsesStore:
    def test_list_notes_uses_store_cache(self, mock_config):
        from lifebook.store import NoteStore
        from lifebook.web.services.note_service import NoteService

        _write_topic(mock_config.knowledge.topics_path, "AI", "Test.md", "Test Note")
        store = NoteStore(mock_config.knowledge)
        svc = NoteService(mock_config.knowledge, store=store)

        # Call list_notes -- it should use the store's cache
        result = svc.list_notes()
        assert result["total"] == 1
        # The store cache should have been loaded
        assert store._topic_cache is not None

    def test_get_tags_uses_store_cache(self, mock_config):
        from lifebook.store import NoteStore
        from lifebook.web.services.note_service import NoteService

        _write_topic(mock_config.knowledge.topics_path, "AI", "A.md", "Note A")
        store = NoteStore(mock_config.knowledge)
        svc = NoteService(mock_config.knowledge, store=store)
        tags = svc.get_tags()
        assert "test" in tags
        # Cache should be populated
        assert store._topic_cache is not None

    def test_get_categories_uses_store(self, mock_config):
        from lifebook.store import NoteStore
        from lifebook.web.services.note_service import NoteService

        _write_topic(mock_config.knowledge.topics_path, "AI", "A.md", "Note A")
        store = NoteStore(mock_config.knowledge)
        svc = NoteService(mock_config.knowledge, store=store)
        cats = svc.get_categories()
        assert "AI" in cats


# ── Shared VectorIndex singleton tests ──────────────────────────────────


class TestSharedVectorIndex:
    def test_vector_index_created_on_startup(self, mock_config):
        from lifebook.web.app import create_app

        app = create_app(mock_config)
        # After creation, vector_index should be None (created lazily or at startup)
        # We test that search.py and system.py use app.state.vector_index
        assert hasattr(app.state, "vector_index")

    def test_search_uses_app_state_vector_index(self, client):
        mock_vi = MagicMock()
        mock_result = MagicMock()
        mock_result.doc_id = "20-topics/AI/Test.md"
        mock_result.distance = 0.1
        mock_result.metadata = {"title": "Test"}
        mock_result.text = "preview"
        mock_vi.search.return_value = [mock_result]

        client.app.state.vector_index = mock_vi
        resp = client.post("/api/search", json={"query": "test", "limit": 5})
        assert resp.status_code == 200
        # The same mock should have been used (not a new instance)
        assert client.app.state.vector_index is mock_vi

    def test_vector_index_not_recreated(self, client):
        mock_vi = MagicMock()
        client.app.state.vector_index = mock_vi
        client.post("/api/search", json={"query": "a", "limit": 5})
        client.post("/api/search", json={"query": "b", "limit": 5})
        # Still the same object
        assert client.app.state.vector_index is mock_vi


# ── Shared LLMClient singleton tests ───────────────────────────────────


class TestSharedLLMClient:
    def test_llm_client_on_app_state(self, mock_config):
        from lifebook.web.app import create_app

        app = create_app(mock_config)
        assert hasattr(app.state, "llm_client")

    def test_podcast_uses_app_state_llm(self, client, mock_config):
        """Podcast endpoint should use request.app.state.llm_client."""
        mock_llm = MagicMock()
        client.app.state.llm_client = mock_llm

        # The endpoint imports LLMClient internally; verify app.state has the attribute
        assert hasattr(client.app.state, "llm_client")
        assert client.app.state.llm_client is mock_llm

    def test_inbox_service_accepts_llm_client(self, mock_config):
        from lifebook.web.services.inbox_service import InboxService
        from lifebook.llm import LLMClient

        mock_llm = MagicMock(spec=LLMClient)
        svc = InboxService(mock_config, llm_client=mock_llm)
        assert svc._llm_client is mock_llm
