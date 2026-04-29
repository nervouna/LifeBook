"""Unit tests for indexer.py."""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from lifebook.indexer import Indexer


@pytest.fixture
def mock_config(tmp_path):
    """Create a mock Config with tmp_path structure."""
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
    """Create a mock VectorIndex."""
    idx = MagicMock()
    idx.upsert = MagicMock()
    idx.upsert_batch = MagicMock()
    idx.delete = MagicMock()
    idx.count.return_value = 0
    return idx


@pytest.fixture
def indexer(mock_config, mock_vector_index):
    """Create an Indexer with mocked vector index."""
    idxr = Indexer(mock_config, interval=60)
    idxr._index = mock_vector_index
    return idxr


def _write_topic_note(topics_dir: Path, category: str, filename: str, title: str) -> Path:
    """Helper: write a minimal topic note."""
    cat_dir = topics_dir / category
    cat_dir.mkdir(parents=True, exist_ok=True)
    note_path = cat_dir / filename
    content = f"""---
title: {title}
status: active
category: {category}
tags:
  - 资讯
  - test-tag
related_keywords:
  - keyword1
---

> Summary of {title}

## 要点

- Point 1
- Point 2

Body text for {title}.
"""
    note_path.write_text(content, encoding="utf-8")
    return note_path


def test_incremental_update_empty(indexer, mock_config):
    """Test update with no topic notes."""
    stats = indexer.incremental_update()
    assert stats == {"upserted": 0, "deleted": 0, "unchanged": 0, "errors": 0}


def test_incremental_update_new_file(indexer, mock_config, mock_vector_index):
    """Test indexing a new topic note."""
    _write_topic_note(mock_config.knowledge.topics_path, "AI技术", "test.md", "Test Note")

    stats = indexer.incremental_update()
    assert stats["upserted"] == 1
    assert stats["unchanged"] == 0
    mock_vector_index.upsert_batch.assert_called_once()

    # Check that the batch call had correct doc_id
    docs = mock_vector_index.upsert_batch.call_args[0][0]
    assert len(docs) == 1
    assert "20-topics/AI技术/test.md" in docs[0]["id"]
    assert "Test Note" in docs[0]["text"]
    assert docs[0]["metadata"]["category"] == "AI技术"


def test_incremental_update_unchanged(indexer, mock_config, mock_vector_index):
    """Test that unchanged files are skipped on second run."""
    _write_topic_note(mock_config.knowledge.topics_path, "AI技术", "test.md", "Test Note")

    # First run: should upsert
    stats1 = indexer.incremental_update()
    assert stats1["upserted"] == 1

    # Second run: unchanged (same mtime)
    mock_vector_index.upsert_batch.reset_mock()
    stats2 = indexer.incremental_update()
    assert stats2["unchanged"] == 1
    assert stats2["upserted"] == 0
    mock_vector_index.upsert_batch.assert_not_called()


def test_incremental_update_modified(indexer, mock_config, mock_vector_index):
    """Test that modified files are re-indexed."""
    note_path = _write_topic_note(
        mock_config.knowledge.topics_path, "AI技术", "test.md", "Test Note"
    )

    # First run
    indexer.incremental_update()
    mock_vector_index.upsert_batch.reset_mock()

    # Modify file (touch with a new mtime)
    time.sleep(0.05)
    note_path.write_text(
        note_path.read_text(encoding="utf-8").replace("Test Note", "Updated Note"),
        encoding="utf-8",
    )

    stats = indexer.incremental_update()
    assert stats["upserted"] == 1
    mock_vector_index.upsert_batch.assert_called_once()


def test_incremental_update_deleted_file(indexer, mock_config, mock_vector_index):
    """Test that deleted files are removed from the index."""
    note_path = _write_topic_note(
        mock_config.knowledge.topics_path, "AI技术", "test.md", "Test Note"
    )

    # First run: index it
    indexer.incremental_update()
    mock_vector_index.delete.reset_mock()

    # Delete the file
    note_path.unlink()

    stats = indexer.incremental_update()
    assert stats["deleted"] == 1
    mock_vector_index.delete.assert_called_once()


def test_incremental_update_skips_non_active(indexer, mock_config, mock_vector_index):
    """Test that non-active notes are skipped."""
    cat_dir = mock_config.knowledge.topics_path / "AI技术"
    cat_dir.mkdir(parents=True, exist_ok=True)
    note = cat_dir / "draft.md"
    note.write_text("""---
title: Draft Note
status: draft
category: AI技术
---
Draft content.
""", encoding="utf-8")

    stats = indexer.incremental_update()
    # File exists but status != active, so text is empty → unchanged
    assert stats["upserted"] == 0
    mock_vector_index.upsert.assert_not_called()


def test_full_rebuild(indexer, mock_config, mock_vector_index):
    """Test full rebuild clears meta and re-indexes."""
    _write_topic_note(mock_config.knowledge.topics_path, "AI技术", "test.md", "Test Note")

    # First run
    indexer.incremental_update()
    mock_vector_index.upsert_batch.reset_mock()

    # Full rebuild should re-index (mtime cleared) but content-hash may skip if same
    stats = indexer.full_rebuild()
    # Content hasn't changed, so content-hash should skip re-embedding
    assert stats["upserted"] == 0
    mock_vector_index.upsert_batch.assert_not_called()


def test_meta_persistence(indexer, mock_config):
    """Test that meta file is saved and loaded correctly."""
    _write_topic_note(mock_config.knowledge.topics_path, "AI技术", "test.md", "Test Note")

    indexer.incremental_update()

    # Check meta file exists
    assert indexer.meta_path.exists()
    meta = json.loads(indexer.meta_path.read_text(encoding="utf-8"))
    assert "indexed" in meta
    assert len(meta["indexed"]) == 1
    entry = next(iter(meta["indexed"].values()))
    assert "mtime" in entry
    assert "content_hash" in entry


def test_start_stop(indexer):
    """Test starting and stopping the background thread."""
    with patch.object(indexer, "incremental_update", return_value={"upserted": 0, "deleted": 0, "unchanged": 0, "errors": 0}):
        indexer.start()
        assert indexer._thread is not None
        assert indexer._thread.is_alive()

        indexer.stop()
        assert not indexer._thread.is_alive()


def test_topics_path_missing(mock_config, mock_vector_index):
    """Test graceful handling when topics path doesn't exist."""
    import shutil
    shutil.rmtree(mock_config.knowledge.topics_path)

    idxr = Indexer(mock_config)
    idxr._index = mock_vector_index
    stats = idxr.incremental_update()
    assert stats == {"upserted": 0, "deleted": 0, "unchanged": 0, "errors": 0}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
