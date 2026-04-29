"""Tests for indexer performance improvements: batch upserts, content-hash, thread safety."""
from __future__ import annotations

import json
import hashlib
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from lifebook.indexer import Indexer


@pytest.fixture
def mock_config(tmp_path):
    knowledge_root = tmp_path / "knowledge"
    topics_dir = knowledge_root / "20-topics"
    topics_dir.mkdir(parents=True)
    state_dir = knowledge_root / ".lifebook"
    state_dir.mkdir(parents=True)

    cfg = MagicMock()
    cfg.knowledge.root = knowledge_root
    cfg.knowledge.topics_path = topics_dir
    cfg.knowledge.state_path = state_dir
    return cfg


@pytest.fixture
def mock_vector_index():
    idx = MagicMock()
    idx.upsert = MagicMock()
    idx.upsert_batch = MagicMock()
    idx.delete = MagicMock()
    idx.count.return_value = 0
    return idx


@pytest.fixture
def indexer(mock_config, mock_vector_index):
    idxr = Indexer(mock_config, interval=60)
    idxr._index = mock_vector_index
    return idxr


def _write_note(topics_dir: Path, category: str, filename: str, title: str, body: str = "body") -> Path:
    cat_dir = topics_dir / category
    cat_dir.mkdir(parents=True, exist_ok=True)
    note = cat_dir / filename
    note.write_text(
        f"---\ntitle: {title}\nstatus: active\ncategory: {category}\ntags:\n  - tag1\n---\n{body}\n",
        encoding="utf-8",
    )
    return note


class TestBatchUpserts:
    """incremental_update should call upsert_batch instead of individual upsert calls."""

    def test_incremental_uses_upsert_batch(self, indexer, mock_config, mock_vector_index):
        _write_note(mock_config.knowledge.topics_path, "AI", "a.md", "A")
        _write_note(mock_config.knowledge.topics_path, "AI", "b.md", "B")

        indexer.incremental_update()

        mock_vector_index.upsert_batch.assert_called_once()
        call_args = mock_vector_index.upsert_batch.call_args
        docs = call_args[0][0]
        assert len(docs) == 2
        ids = {d["id"] for d in docs}
        assert any("a.md" in i for i in ids)
        assert any("b.md" in i for i in ids)
        # Individual upsert should NOT be called
        mock_vector_index.upsert.assert_not_called()

    def test_incremental_no_batch_when_no_changes(self, indexer, mock_config, mock_vector_index):
        indexer.incremental_update()
        mock_vector_index.upsert_batch.assert_not_called()

    def test_incremental_batch_excludes_errors(self, indexer, mock_config, mock_vector_index):
        _write_note(mock_config.knowledge.topics_path, "AI", "a.md", "A")
        _write_note(mock_config.knowledge.topics_path, "AI", "b.md", "B")

        call_count = 0
        original_extract = indexer._extract_doc

        def patched_extract(md_path):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("extract fail")
            return original_extract(md_path)

        indexer._extract_doc = patched_extract
        stats = indexer.incremental_update()

        assert stats["errors"] == 1
        mock_vector_index.upsert_batch.assert_called_once()
        docs = mock_vector_index.upsert_batch.call_args[0][0]
        assert len(docs) == 1


class TestContentHashFullRebuild:
    """full_rebuild should skip re-embedding when content hash hasn't changed."""

    def test_full_rebuild_skips_unchanged_content(self, indexer, mock_config, mock_vector_index):
        note = _write_note(mock_config.knowledge.topics_path, "AI", "a.md", "A", body="hello")

        # First run
        indexer.incremental_update()
        mock_vector_index.upsert_batch.reset_mock()

        # Full rebuild: meta is cleared, but content hash should skip re-embedding
        stats = indexer.full_rebuild()

        meta = indexer._load_meta()
        indexed = meta.get("indexed", {})
        key = next(k for k in indexed if "a.md" in k)
        assert indexed[key].get("content_hash") is not None
        # Content unchanged, so no batch upsert
        mock_vector_index.upsert_batch.assert_not_called()
        assert stats["upserted"] == 0

    def test_full_rebuild_reembeds_changed_content(self, indexer, mock_config, mock_vector_index):
        note = _write_note(mock_config.knowledge.topics_path, "AI", "a.md", "A", body="hello")
        indexer.incremental_update()
        mock_vector_index.upsert_batch.reset_mock()

        # Change the note body
        note.write_text(
            note.read_text(encoding="utf-8").replace("hello", "world"),
            encoding="utf-8",
        )

        stats = indexer.full_rebuild()

        mock_vector_index.upsert_batch.assert_called_once()
        docs = mock_vector_index.upsert_batch.call_args[0][0]
        assert len(docs) == 1
        assert stats["upserted"] == 1

    def test_incremental_uses_content_hash_too(self, indexer, mock_config, mock_vector_index):
        note = _write_note(mock_config.knowledge.topics_path, "AI", "a.md", "A", body="content")
        indexer.incremental_update()
        mock_vector_index.upsert_batch.reset_mock()

        # Touch file to change mtime but keep content the same
        note.touch()
        time_mod = note.stat().st_mtime
        # Force mtime update
        import os, time
        os.utime(note, (time_mod + 1, time_mod + 1))

        stats = indexer.incremental_update()
        mock_vector_index.upsert_batch.assert_not_called()
        assert stats["unchanged"] == 1


class TestMetaFileLocking:
    """_save_meta should use fcntl.flock for safe concurrent writes."""

    def test_save_meta_creates_lock_sidecar(self, indexer, mock_config):
        indexer._save_meta({"indexed": {}})
        lock_path = indexer.meta_path.with_suffix(indexer.meta_path.suffix + ".lock")
        assert lock_path.parent.exists()


class TestThreadSafeModelInit:
    """VectorIndex.model property should be thread-safe via double-checked locking."""

    def test_concurrent_model_init(self):
        from lifebook.vector import VectorIndex

        with patch("lifebook.vector.chromadb") as mock_chromadb, \
             patch("lifebook.vector.SentenceTransformer") as mock_st:
            mock_chromadb.config = MagicMock()
            mock_client = MagicMock()
            mock_collection = MagicMock()
            mock_collection.count.return_value = 0
            mock_client.get_or_create_collection.return_value = mock_collection
            mock_chromadb.PersistentClient.return_value = mock_client

            call_count = 0
            real_init = lambda name: MagicMock()
            original_side_effect = mock_st.side_effect

            def counting_init(name=None):
                nonlocal call_count
                call_count += 1
                import time
                time.sleep(0.01)  # simulate slow init
                return MagicMock()

            mock_st.side_effect = counting_init

            vi = VectorIndex(Path("/tmp/test_vs"))
            vi._model = None  # Reset so lazy init triggers

            results = []

            def access_model():
                m = vi.model
                results.append(m)

            threads = [threading.Thread(target=access_model) for _ in range(5)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            # Model should only be initialized once despite concurrent access
            assert call_count == 1
            # All threads should get the same model instance
            assert len(set(id(r) for r in results)) == 1

    def test_model_property_returns_same_instance(self):
        from lifebook.vector import VectorIndex

        with patch("lifebook.vector.chromadb") as mock_chromadb, \
             patch("lifebook.vector.SentenceTransformer") as mock_st:
            mock_chromadb.config = MagicMock()
            mock_client = MagicMock()
            mock_collection = MagicMock()
            mock_collection.count.return_value = 0
            mock_client.get_or_create_collection.return_value = mock_collection
            mock_chromadb.PersistentClient.return_value = mock_client
            mock_st.return_value = MagicMock()

            vi = VectorIndex(Path("/tmp/test_vs2"))
            vi._model = None

            m1 = vi.model
            m2 = vi.model
            assert m1 is m2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
