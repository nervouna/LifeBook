"""Coverage tests for ingest.py."""
from __future__ import annotations

import hashlib
from pathlib import Path

from lifebook.ingest import ingest_url, ingest_text, ingest_image
from lifebook.notes import read_note


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


class TestIngestImage:
    def test_saves_image_and_creates_inbox_record(self, tmp_path: Path):
        from lifebook.config import KnowledgeConfig
        cfg = KnowledgeConfig(root=tmp_path)
        image_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50
        note_path = ingest_image(cfg, image_bytes, "image/png")

        assert note_path.exists()
        post = read_note(note_path)
        assert post.get("source_type") == "image"
        assert post.get("status") == "inbox"
        assert post.get("image_mime") == "image/png"

        expected_hash = hashlib.sha256(image_bytes).hexdigest()
        assert post.get("image_hash") == expected_hash

        img_path = tmp_path / "10-sources" / "images" / f"{expected_hash}.png"
        assert img_path.exists()
        assert img_path.read_bytes() == image_bytes

    def test_dedup_by_hash(self, tmp_path: Path):
        from lifebook.config import KnowledgeConfig
        cfg = KnowledgeConfig(root=tmp_path)
        image_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50

        path1 = ingest_image(cfg, image_bytes, "image/png")
        path2 = ingest_image(cfg, image_bytes, "image/png")

        assert path1 != path2
        expected_hash = hashlib.sha256(image_bytes).hexdigest()
        img_dir = tmp_path / "10-sources" / "images"
        assert len(list(img_dir.glob(f"{expected_hash}*"))) == 1

    def test_with_title_and_caption(self, tmp_path: Path):
        from lifebook.config import KnowledgeConfig
        cfg = KnowledgeConfig(root=tmp_path)
        note_path = ingest_image(
            cfg, b"\x00" * 10, "image/jpeg",
            title_hint="My Photo", caption="A nice photo",
        )
        post = read_note(note_path)
        assert post.get("title") == "My Photo"
        assert "A nice photo" in post.content
