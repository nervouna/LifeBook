"""Tests for inbox process SSE endpoints."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


def _write_source(sources_dir: Path, filename: str, status: str = "inbox"):
    path = sources_dir / filename
    lines = ["---", f"status: {status}", "source_type: manual", "created: '2026-01-01T00:00:00+08:00'", "---", "content"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class TestProcessSingle:
    @patch("lifebook.web.services.inbox_service.Executor")
    def test_process_file(self, mock_exec_cls, client, mock_config):
        _write_source(mock_config.knowledge.sources_path, "test.md")
        mock_exec = MagicMock()
        result = MagicMock()
        result.ok = True
        result.topic_path = mock_config.knowledge.topics_path / "AI技术" / "Test.md"
        result.skipped_reason = None
        result.error = None
        mock_exec.process_file.return_value = result
        mock_exec_cls.return_value = mock_exec

        with client.stream("POST", "/api/inbox/10-sources/test.md/process") as resp:
            assert resp.status_code == 200
