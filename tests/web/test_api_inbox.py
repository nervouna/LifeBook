"""Tests for inbox API endpoints."""
from __future__ import annotations

from pathlib import Path

import pytest


def _write_source(sources_dir: Path, filename: str, status: str = "inbox", source_type: str = "manual", **meta):
    path = sources_dir / filename
    lines = ["---"]
    lines.append(f"status: {status}")
    lines.append(f"source_type: {source_type}")
    lines.append(f"created: '2026-01-01T00:00:00+08:00'")
    for k, v in meta.items():
        lines.append(f"{k}: {v}")
    lines.append("---")
    lines.append("Some content")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class TestListInbox:
    def test_empty(self, client):
        resp = client.get("/api/inbox")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0

    def test_lists_inbox(self, client, mock_config):
        _write_source(mock_config.knowledge.sources_path, "a.md")
        _write_source(mock_config.knowledge.sources_path, "b.md", status="processed")
        resp = client.get("/api/inbox")
        data = resp.json()
        assert data["total"] == 1

    def test_filter_by_status(self, client, mock_config):
        _write_source(mock_config.knowledge.sources_path, "a.md", status="inbox")
        _write_source(mock_config.knowledge.sources_path, "b.md", status="processing")
        resp = client.get("/api/inbox", params={"status": "inbox"})
        data = resp.json()
        assert data["total"] == 1


class TestIngest:
    def test_ingest_text(self, client, mock_config):
        resp = client.post("/api/inbox", json={"url_or_text": "test content"})
        assert resp.status_code == 200
        data = resp.json()
        assert "path" in data
