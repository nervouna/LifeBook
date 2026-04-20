"""Coverage tests for ingest.py."""
from __future__ import annotations

from pathlib import Path

from lifebook.ingest import ingest_url, ingest_text


class TestIngestUrl:
    def test_creates_inbox_file(self, tmp_path: Path):
        from lifebook.config import KnowledgeConfig
        cfg = KnowledgeConfig(root=tmp_path)
        path = ingest_url(cfg, "https://example.com/page", source_type="chat_link")
        assert path.exists()
        assert "inbox" in path.read_text()

    def test_with_title(self, tmp_path: Path):
        from lifebook.config import KnowledgeConfig
        cfg = KnowledgeConfig(root=tmp_path)
        path = ingest_url(cfg, "https://example.com", title_hint="My Title")
        content = path.read_text()
        assert "My Title" in content


class TestIngestText:
    def test_creates_inbox_file(self, tmp_path: Path):
        from lifebook.config import KnowledgeConfig
        cfg = KnowledgeConfig(root=tmp_path)
        path = ingest_text(cfg, "some text content")
        assert path.exists()
        assert "some text content" in path.read_text()

    def test_with_title(self, tmp_path: Path):
        from lifebook.config import KnowledgeConfig
        cfg = KnowledgeConfig(root=tmp_path)
        path = ingest_text(cfg, "body", title_hint="Title")
        assert "Title" in path.read_text()
