"""Tests for note API endpoints."""
from __future__ import annotations

from pathlib import Path

import frontmatter
import pytest


def _write_topic(topics_dir: Path, category: str, filename: str, title: str, body: str = "content", **meta):
    d = topics_dir / category
    d.mkdir(parents=True, exist_ok=True)
    path = d / filename
    post = frontmatter.Post(body)
    post["title"] = title
    post["category"] = category
    post["created"] = "2026-01-01T00:00:00+08:00"
    for k, v in meta.items():
        post[k] = v
    path.write_text(frontmatter.dumps(post, sort_keys=False), encoding="utf-8")
    return path


class TestListNotes:
    def test_empty(self, client):
        resp = client.get("/api/notes")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["items"] == []

    def test_lists_notes(self, client, mock_config):
        _write_topic(mock_config.knowledge.topics_path, "AI技术", "Test-Note.md", "Test Note")
        resp = client.get("/api/notes")
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["title"] == "Test Note"

    def test_filter_by_category(self, client, mock_config):
        _write_topic(mock_config.knowledge.topics_path, "AI技术", "A.md", "Note A")
        _write_topic(mock_config.knowledge.topics_path, "半导体", "B.md", "Note B")
        resp = client.get("/api/notes", params={"category": "AI技术"})
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["category"] == "AI技术"

    def test_pagination(self, client, mock_config):
        for i in range(5):
            _write_topic(mock_config.knowledge.topics_path, "AI技术", f"Note-{i}.md", f"Note {i}")
        resp = client.get("/api/notes", params={"page": 1, "per_page": 2})
        data = resp.json()
        assert len(data["items"]) == 2
        assert data["total"] == 5


class TestGetNote:
    def test_returns_detail(self, client, mock_config):
        path = _write_topic(mock_config.knowledge.topics_path, "AI技术", "Test.md", "Test Note", "body content")
        rel = str(path.relative_to(mock_config.knowledge.root))
        resp = client.get(f"/api/notes/{rel}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "Test Note"
        assert data["body"] == "body content"

    def test_not_found(self, client):
        resp = client.get("/api/notes/20-topics/AI技术/Nonexistent.md")
        assert resp.status_code == 404


class TestUpdateNote:
    def test_updates_tags(self, client, mock_config):
        path = _write_topic(mock_config.knowledge.topics_path, "AI技术", "Test.md", "Test Note")
        rel = str(path.relative_to(mock_config.knowledge.root))
        resp = client.put(f"/api/notes/{rel}", json={"tags": ["new-tag"]})
        assert resp.status_code == 200
        data = resp.json()
        assert "new-tag" in data["metadata"]["tags"]
