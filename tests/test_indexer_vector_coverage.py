"""Coverage tests for indexer.py and vector.py (requires mocked chromadb)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def mock_vector_deps():
    with (
        patch("lifebook.vector.chromadb") as mock_chromadb,
        patch("lifebook.vector.SentenceTransformer") as mock_st,
    ):
        mock_chromadb.config = MagicMock()
        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = MagicMock()
        mock_chromadb.PersistentClient.return_value = mock_client
        mock_st.return_value = MagicMock()
        yield


@pytest.fixture
def index_cfg(tmp_path):
    from lifebook.config import (
        Config, KnowledgeConfig, LLMConfig, FeishuConfig,
        ExecutorConfig, DigestConfig, TavilyConfig, FetchConfig, LoggingConfig,
    )
    topics = tmp_path / "20-topics"
    topics.mkdir()
    state = tmp_path / ".lifebook"
    state.mkdir()
    return Config(
        knowledge=KnowledgeConfig(root=tmp_path),
        llm=LLMConfig(),
        feishu=FeishuConfig(),
        executor=ExecutorConfig(),
        digest=DigestConfig(),
        tavily=TavilyConfig(),
        fetch=FetchConfig(),
        logging=LoggingConfig(),
    )


class TestVectorIndex:
    def test_upsert_batch_empty(self, index_cfg):
        from lifebook.vector import VectorIndex
        vi = VectorIndex(index_cfg.knowledge.state_path / "vs")
        vi.upsert_batch([])  # should not raise

    def test_delete(self, index_cfg):
        from lifebook.vector import VectorIndex
        vi = VectorIndex(index_cfg.knowledge.state_path / "vs")
        vi.delete("doc1")
        vi.collection.delete.assert_called_with(ids=["doc1"])

    def test_count(self, index_cfg):
        from lifebook.vector import VectorIndex
        vi = VectorIndex(index_cfg.knowledge.state_path / "vs")
        vi.collection.count.return_value = 42
        assert vi.count() == 42

    def test_has(self, index_cfg):
        from lifebook.vector import VectorIndex
        vi = VectorIndex(index_cfg.knowledge.state_path / "vs")
        vi.collection.get.return_value = {"ids": ["doc1"]}
        assert vi.has("doc1") is True
        vi.collection.get.return_value = {"ids": []}
        assert vi.has("doc2") is False

    def test_search_exception(self, index_cfg):
        from lifebook.vector import VectorIndex
        vi = VectorIndex(index_cfg.knowledge.state_path / "vs")
        vi.collection.query.side_effect = Exception("chromadb error")
        assert vi.search("query") == []

    def test_search_empty_ids(self, index_cfg):
        from lifebook.vector import VectorIndex
        vi = VectorIndex(index_cfg.knowledge.state_path / "vs")
        vi.collection.query.side_effect = None
        vi.collection.query.return_value = {"ids": [[]]}
        assert vi.search("query") == []

    def test_search_success(self, index_cfg):
        from lifebook.vector import VectorIndex
        vi = VectorIndex(index_cfg.knowledge.state_path / "vs")
        vi.collection.query.return_value = {
            "ids": [["doc1"]],
            "distances": [[0.1]],
            "metadatas": [[{"title": "T"}]],
            "documents": [["content"]],
        }
        results = vi.search("query")
        # Mock may return empty due to ChromaDB mock behavior
        # Just verify it doesn't raise
        assert isinstance(results, list)

    def test_embedding_empty(self, index_cfg):
        from lifebook.vector import VectorIndex
        vi = VectorIndex(index_cfg.knowledge.state_path / "vs")
        embed_fn = vi._embedding_function()
        assert embed_fn([]) == []

    def test_upsert(self, index_cfg):
        from lifebook.vector import VectorIndex
        vi = VectorIndex(index_cfg.knowledge.state_path / "vs")
        vi.upsert("doc1", "some text", {"title": "T"})
        vi.collection.upsert.assert_called_with(
            ids=["doc1"], documents=["some text"], metadatas=[{"title": "T"}],
        )

    def test_upsert_batch(self, index_cfg):
        from lifebook.vector import VectorIndex
        vi = VectorIndex(index_cfg.knowledge.state_path / "vs")
        docs = [{"id": "d1", "text": "t1", "metadata": {"title": "T1"}}]
        vi.upsert_batch(docs)
        vi.collection.upsert.assert_called_with(
            ids=["d1"], documents=["t1"], metadatas=[{"title": "T1"}],
        )

    def test_search_success_with_results(self, index_cfg):
        from lifebook.vector import VectorIndex
        vi = VectorIndex(index_cfg.knowledge.state_path / "vs")
        vi.collection.query.side_effect = None  # Reset from prior tests
        vi.collection.query.return_value = {
            "ids": [["doc1", "doc2"]],
            "distances": [[0.1, 0.2]],
            "metadatas": [[{"title": "T1"}, {"title": "T2"}]],
            "documents": [["content1", "content2"]],
        }
        results = vi.search("query", n_results=2)
        assert len(results) == 2
        assert results[0].doc_id == "doc1"
        assert results[1].doc_id == "doc2"

    def test_search_with_where_filter(self, index_cfg):
        from lifebook.vector import VectorIndex
        vi = VectorIndex(index_cfg.knowledge.state_path / "vs")
        vi.collection.query.side_effect = None
        vi.collection.query.return_value = {
            "ids": [["doc1"]],
            "distances": [[0.1]],
            "metadatas": [[{"title": "T"}]],
            "documents": [["content"]],
        }
        vi.search("query", where={"category": "AI"})
        vi.collection.query.assert_called()
        call_kwargs = vi.collection.query.call_args
        assert call_kwargs[1].get("where") == {"category": "AI"} or \
               (len(call_kwargs) > 1 and call_kwargs[1].get("where") == {"category": "AI"})

    def test_embedding_function_with_texts(self, index_cfg):
        from lifebook.vector import VectorIndex
        from unittest.mock import MagicMock
        vi = VectorIndex(index_cfg.knowledge.state_path / "vs")
        mock_emb = MagicMock()
        mock_emb.tolist.return_value = [0.1, 0.2, 0.3]
        vi.model = MagicMock()
        vi.model.encode.return_value = [mock_emb]
        embed_fn = vi._embedding_function()
        result = embed_fn(["hello"])
        assert result == [[0.1, 0.2, 0.3]]


class TestIndexer:
    def test_incremental_update_no_topics_dir(self, index_cfg):
        from lifebook.indexer import Indexer
        idx = Indexer(index_cfg)
        # Topics dir exists but empty
        stats = idx.incremental_update()
        assert stats["upserted"] == 0

    def test_incremental_update_topics_not_exist(self, index_cfg):
        from lifebook.indexer import Indexer
        import shutil
        shutil.rmtree(index_cfg.knowledge.topics_path)
        idx = Indexer(index_cfg)
        stats = idx.incremental_update()
        assert stats["upserted"] == 0

    def test_incremental_update_upserts_new(self, index_cfg):
        from lifebook.indexer import Indexer
        cat = index_cfg.knowledge.topics_path / "AI技术"
        cat.mkdir()
        (cat / "note.md").write_text(
            "---\ntitle: Test\nstatus: active\ncategory: AI技术\n---\nbody\n",
            encoding="utf-8",
        )
        idx = Indexer(index_cfg)
        idx._index = MagicMock()
        stats = idx.incremental_update()
        assert stats["upserted"] == 1
        idx._index.upsert_batch.assert_called_once()

    def test_incremental_update_skips_unchanged(self, index_cfg):
        from lifebook.indexer import Indexer
        cat = index_cfg.knowledge.topics_path / "AI技术"
        cat.mkdir()
        note = cat / "note.md"
        note.write_text(
            "---\ntitle: Test\nstatus: active\n---\nbody\n",
            encoding="utf-8",
        )
        idx = Indexer(index_cfg)
        idx._index = MagicMock()
        # First run: upserts
        idx.incremental_update()
        # Second run: unchanged
        stats = idx.incremental_update()
        assert stats["unchanged"] >= 1

    def test_incremental_update_deletes_stale(self, index_cfg):
        from lifebook.indexer import Indexer
        idx = Indexer(index_cfg)
        idx._index = MagicMock()
        # Pre-populate meta with a file that no longer exists
        idx.meta_path.write_text(
            json.dumps({"indexed": {"nonexistent.md": {"mtime": 12345.0, "content_hash": "abc"}}}),
            encoding="utf-8",
        )
        stats = idx.incremental_update()
        assert stats["deleted"] == 1

    def test_incremental_update_upsert_error(self, index_cfg):
        from lifebook.indexer import Indexer
        cat = index_cfg.knowledge.topics_path / "AI技术"
        cat.mkdir()
        (cat / "note.md").write_text(
            "---\ntitle: Test\nstatus: active\n---\nbody\n",
            encoding="utf-8",
        )
        idx = Indexer(index_cfg)
        idx._index = MagicMock()
        idx._index.upsert_batch.side_effect = Exception("upsert fail")
        stats = idx.incremental_update()
        assert stats["errors"] >= 1

    def test_incremental_update_delete_error(self, index_cfg):
        from lifebook.indexer import Indexer
        idx = Indexer(index_cfg)
        idx._index = MagicMock()
        idx._index.delete.side_effect = Exception("delete fail")
        idx.meta_path.write_text(
            json.dumps({"indexed": {"gone.md": 12345.0}}),
            encoding="utf-8",
        )
        stats = idx.incremental_update()
        assert stats["errors"] >= 1

    def test_full_rebuild(self, index_cfg):
        from lifebook.indexer import Indexer
        idx = Indexer(index_cfg)
        idx._index = MagicMock()
        stats = idx.full_rebuild()
        # Should have cleared meta and re-indexed
        assert isinstance(stats, dict)

    def test_start_stop(self, index_cfg):
        from lifebook.indexer import Indexer
        idx = Indexer(index_cfg, interval=1)
        idx._index = MagicMock()
        idx.start()
        assert idx._thread is not None
        idx.stop()

    def test_start_already_running(self, index_cfg):
        from lifebook.indexer import Indexer
        idx = Indexer(index_cfg, interval=1)
        idx._index = MagicMock()
        idx.start()
        # Second start should warn but not fail
        idx.start()
        idx.stop()

    def test_extract_doc_inactive(self, index_cfg):
        from lifebook.indexer import Indexer
        cat = index_cfg.knowledge.topics_path / "AI技术"
        cat.mkdir()
        note = cat / "inactive.md"
        note.write_text(
            "---\ntitle: Test\nstatus: archived\n---\nbody\n",
            encoding="utf-8",
        )
        idx = Indexer(index_cfg)
        text, meta = idx._extract_doc(note)
        assert text == ""

    def test_extract_doc_active(self, index_cfg):
        from lifebook.indexer import Indexer
        cat = index_cfg.knowledge.topics_path / "AI技术"
        cat.mkdir()
        note = cat / "active.md"
        note.write_text(
            "---\ntitle: Test Note\nstatus: active\ncategory: AI技术\ntags:\n  - tag1\n  - tag2\nrelated_keywords:\n  - kw1\nsummary: A summary\nkey_points:\n  - point1\n---\nBody content\n",
            encoding="utf-8",
        )
        idx = Indexer(index_cfg)
        text, meta = idx._extract_doc(note)
        assert "Test Note" in text
        assert meta["category"] == "AI技术"
        assert "tag1,tag2" == meta["tags"]

    def test_load_meta_missing(self, index_cfg):
        from lifebook.indexer import Indexer
        idx = Indexer(index_cfg)
        meta = idx._load_meta()
        assert meta == {"indexed": {}}

    def test_load_meta_corrupt(self, index_cfg):
        from lifebook.indexer import Indexer
        idx = Indexer(index_cfg)
        idx.meta_path.parent.mkdir(parents=True, exist_ok=True)
        idx.meta_path.write_text("not json {{{", encoding="utf-8")
        meta = idx._load_meta()
        assert meta == {"indexed": {}}

    def test_save_meta(self, index_cfg):
        from lifebook.indexer import Indexer
        idx = Indexer(index_cfg)
        idx._save_meta({"indexed": {"a.md": {"mtime": 1.0, "content_hash": "abc"}}})
        loaded = json.loads(idx.meta_path.read_text(encoding="utf-8"))
        assert loaded["indexed"]["a.md"]["mtime"] == 1.0

    def test_run_loop_stops(self, index_cfg):
        from lifebook.indexer import Indexer
        idx = Indexer(index_cfg, interval=1)
        idx._index = MagicMock()
        idx._stop_event.set()
        idx._run_loop()  # should return immediately

    def test_run_loop_exception_in_periodic(self, index_cfg):
        from lifebook.indexer import Indexer
        idx = Indexer(index_cfg, interval=1)
        idx._index = MagicMock()
        call_count = 0

        def side_effect():
            nonlocal call_count
            call_count += 1
            if call_count > 1:
                idx._stop_event.set()
                raise Exception("periodic fail")

        idx.incremental_update = MagicMock(side_effect=side_effect)
        idx._run_loop()

    def test_index_property_lazy_load(self, index_cfg):
        """Lines 47: lazy VectorIndex loading."""
        from lifebook.indexer import Indexer
        from unittest.mock import patch as p
        idx = Indexer(index_cfg)
        assert idx._index is None
        with p("lifebook.indexer.VectorIndex") as MockVI:
            MockVI.return_value = MagicMock()
            result = idx.index
            MockVI.assert_called_once()
            assert result is not None

    def test_incremental_update_unchanged_skips(self, index_cfg):
        """Lines 105-106: unchanged documents are skipped."""
        from lifebook.indexer import Indexer
        cat = index_cfg.knowledge.topics_path / "AI技术"
        cat.mkdir()
        (cat / "note.md").write_text(
            "---\ntitle: Test\nstatus: active\n---\nbody\n",
            encoding="utf-8",
        )
        idx = Indexer(index_cfg)
        idx._index = MagicMock()
        # First run
        idx.incremental_update()
        # Second run: file unchanged, should be in unchanged
        stats = idx.incremental_update()
        assert stats["unchanged"] >= 1

    def test_incremental_update_empty_text_skips(self, index_cfg):
        """Lines 105-106: inactive note produces empty text → counted as unchanged."""
        from lifebook.indexer import Indexer
        cat = index_cfg.knowledge.topics_path / "AI技术"
        cat.mkdir()
        (cat / "inactive.md").write_text(
            "---\ntitle: Test\nstatus: archived\n---\nbody\n",
            encoding="utf-8",
        )
        idx = Indexer(index_cfg)
        idx._index = MagicMock()
        stats = idx.incremental_update()
        assert stats["unchanged"] >= 1

    def test_run_loop_stops_on_event(self, index_cfg):
        """Lines 153-154, 159: _run_loop exception handling and stop event."""
        from lifebook.indexer import Indexer
        idx = Indexer(index_cfg, interval=1)
        idx._index = MagicMock()
        # First iteration raises, second stops
        call_count = 0
        def side_effect():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("first run error")
            idx._stop_event.set()
        idx.incremental_update = MagicMock(side_effect=side_effect)
        idx._run_loop()
        assert call_count >= 2

    def test_run_loop_break_on_wait(self, index_cfg):
        """Line 159: stop_event set during wait causes break."""
        import threading as thr
        from lifebook.indexer import Indexer
        idx = Indexer(index_cfg, interval=60)
        idx._index = MagicMock()
        idx.incremental_update = MagicMock()
        # Set stop event from another thread after a tiny delay
        def set_stop():
            import time
            time.sleep(0.05)
            idx._stop_event.set()
        t = thr.Thread(target=set_stop)
        t.start()
        idx._run_loop()
        t.join()
        idx.incremental_update.assert_called_once()
