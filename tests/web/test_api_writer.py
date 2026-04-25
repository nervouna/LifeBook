"""Tests for writer API endpoints."""
from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest


class TestWriterStatus:
    @patch("lifebook.web.services.writer_service.LLMClient")
    def test_no_active_draft(self, mock_llm_cls, client, mock_config):
        resp = client.get("/api/writer/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["active"] is False

    @patch("lifebook.web.services.writer_service.LLMClient")
    def test_active_draft(self, mock_llm_cls, client, mock_config):
        draft_meta = mock_config.knowledge.publish_path / "draft.json"
        draft_meta.write_text('{"stage": "concept", "title": "Test"}', encoding="utf-8")
        resp = client.get("/api/writer/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["active"] is True
        assert data["stage"] == "concept"


class TestWriterStart:
    @patch("lifebook.web.services.writer_service.LLMClient")
    def test_start_session(self, mock_llm_cls, client, mock_config):
        mock_llm = MagicMock()
        mock_llm.structured_call.return_value = {
            "topic": "Test Topic",
            "thesis": "Test thesis",
            "audience": "General",
            "concept_text": "A concept",
        }
        mock_llm_cls.return_value = mock_llm
        resp = client.post("/api/writer/start", json={"idea": "write about AI"})
        assert resp.status_code == 200
        data = resp.json()
        assert "reply" in data


class TestWriterChat:
    @patch("lifebook.web.services.writer_service.LLMClient")
    def test_chat_without_active_session(self, mock_llm_cls, client, mock_config):
        resp = client.post("/api/writer/chat", json={"message": "hello"})
        assert resp.status_code == 200
        data = resp.json()
        assert "没有" in data["reply"]
