"""Tests for system and podcast API endpoints."""
from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest


class TestSystemDoctor:
    def test_doctor(self, client):
        resp = client.get("/api/system/doctor")
        assert resp.status_code == 200
        data = resp.json()
        assert "checks" in data


class TestSystemStats:
    def test_stats(self, client, mock_config):
        resp = client.get("/api/system/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "topic_count" in data
        assert "inbox_count" in data
        assert "categories" in data


class TestCategories:
    def test_empty(self, client):
        resp = client.get("/api/system/categories")
        assert resp.status_code == 200

    def test_has_categories(self, client, mock_config):
        (mock_config.knowledge.topics_path / "AI技术").mkdir()
        resp = client.get("/api/system/categories")
        data = resp.json()
        assert "AI技术" in data["categories"]


class TestTags:
    def test_empty(self, client):
        resp = client.get("/api/system/tags")
        assert resp.status_code == 200
