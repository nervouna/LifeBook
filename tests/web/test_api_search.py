"""Tests for search API endpoint."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest


class TestSearch:
    def test_empty_query(self, client):
        resp = client.post("/api/search", json={"query": "", "limit": 10})
        assert resp.status_code == 200
        data = resp.json()
        assert data["results"] == []

    def test_returns_results(self, client):
        mock_vi = MagicMock()
        mock_result = MagicMock()
        mock_result.doc_id = "20-topics/AI技术/Test.md"
        mock_result.distance = 0.1
        mock_result.metadata = {"title": "Test Note"}
        mock_result.text = "Some preview text"
        mock_vi.search.return_value = [mock_result]

        # Inject mock VectorIndex into app state before request
        client.app.state.vector_index = mock_vi

        resp = client.post("/api/search", json={"query": "test", "limit": 10})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["results"]) == 1
        assert data["results"][0]["title"] == "Test Note"
