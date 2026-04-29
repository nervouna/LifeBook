"""Coverage tests for store.py missing lines."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from lifebook.config import KnowledgeConfig
from lifebook.notes import new_post, write_note
from lifebook.store import NoteStore


def _write_source(sources_dir: Path, filename: str, content: str = "", **meta) -> Path:
    path = sources_dir / filename
    lines = ["---"]
    for k, v in meta.items():
        lines.append(f"{k}: {v}")
    lines.append("---")
    lines.append(content)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def store(tmp_path):
    sources = tmp_path / "10-sources"
    sources.mkdir()
    topics = tmp_path / "20-topics"
    topics.mkdir()
    cfg = KnowledgeConfig(root=tmp_path)
    return NoteStore(cfg)


def _create_topic(topics_dir: Path, filename: str, **kwargs):
    title = kwargs.pop("title", filename.replace(".md", ""))
    body = kwargs.pop("body", "默认内容")
    post = new_post(body, title=title, **kwargs)
    write_note(topics_dir / filename, post)


class TestScanInboxCorrupt:
    def test_skips_corrupt_files(self, store):
        _write_source(store.cfg.sources_path, "good.md", status="inbox")
        bad = store.cfg.sources_path / "bad.md"
        bad.write_bytes(b"\x00\x01\x80\x81\xfe\xff")
        result = store.scan_inbox()
        assert len(result) == 1
        assert result[0].name == "good.md"


class TestRecoverStaleEdgeCases:
    def test_missing_processing_at(self, store):
        _write_source(store.cfg.sources_path, "no_pa.md", status="processing")
        result = store.recover_stale(timeout_minutes=10)
        assert len(result) == 1
        assert "(no processing_at)" in result[0][1]

    def test_bad_timestamp(self, store):
        _write_source(store.cfg.sources_path, "bad_ts.md", status="processing", processing_at="not-a-date")
        result = store.recover_stale(timeout_minutes=10)
        assert len(result) == 1
        assert "bad timestamp" in result[0][1]

    def test_datetime_object_processing_at(self, store):
        from datetime import datetime, timezone, timedelta
        old_dt = datetime(2020, 1, 1, tzinfo=timezone(timedelta(hours=8)))
        path = _write_source(store.cfg.sources_path, "dt.md", status="processing")
        from lifebook.notes import read_note
        post = read_note(path)
        post["processing_at"] = old_dt
        write_note(path, post)
        result = store.recover_stale(timeout_minutes=10)
        assert len(result) == 1

    def test_missing_sources_dir(self, store):
        shutil.rmtree(store.cfg.sources_path)
        result = store.recover_stale()
        assert result == []

    def test_corrupt_file_skipped(self, store):
        (store.cfg.sources_path / "bad.md").write_bytes(b"\x00\x01\x80\x81")
        result = store.recover_stale()
        assert result == []

    def test_non_processing_skipped(self, store):
        _write_source(store.cfg.sources_path, "inbox.md", status="inbox")
        result = store.recover_stale()
        assert result == []


class TestFindRelatedEdgeCases:
    def test_deduplicates_titles(self, store):
        td = store.cfg.topics_path
        cat = td / "AI技术"
        cat.mkdir()
        (cat / "a.md").write_text("---\ntitle: Same Title\ntags: [ai]\n---\nbody\n", encoding="utf-8")
        (cat / "b.md").write_text("---\ntitle: Same Title\ntags: [ai]\n---\nbody\n", encoding="utf-8")
        result = store.find_related(["ai"])
        assert result.count("Same Title") == 1

    def test_max_hits_limit(self, store):
        td = store.cfg.topics_path
        cat = td / "AI技术"
        cat.mkdir()
        for i in range(10):
            (cat / f"n{i}.md").write_text(
                f"---\ntitle: Note {i}\ntags: [ai-tech]\n---\nbody\n",
                encoding="utf-8",
            )
        result = store.find_related(["ai-tech"], max_hits=2)
        assert len(result) <= 2


class TestFindSourceUrl:
    def test_empty_url_returns_none(self, store):
        assert store.find_by_source_url("") is None

    def test_finds_existing(self, store):
        td = store.cfg.topics_path
        cat = td / "AI技术"
        cat.mkdir()
        (cat / "note.md").write_text(
            "---\ntitle: Test\nsource_url: https://example.com\n---\nbody\n",
            encoding="utf-8",
        )
        result = store.find_by_source_url("https://example.com")
        assert result is not None

    def test_no_match_returns_none(self, store):
        td = store.cfg.topics_path
        cat = td / "AI技术"
        cat.mkdir()
        (cat / "note.md").write_text(
            "---\ntitle: Test\nsource_url: https://other.com\n---\nbody\n",
            encoding="utf-8",
        )
        assert store.find_by_source_url("https://example.com") is None


class TestTopicCacheInvalidation:
    def test_cache_invalidated_on_topic_write(self, store):
        td = store.cfg.topics_path
        cat = td / "AI技术"
        cat.mkdir()
        path = cat / "test.md"
        post = new_post("body", title="Test")
        store.write_note(path, post)
        assert store._topic_cache is None

    def test_cache_not_invalidated_on_non_topic_write(self, store):
        store._load_topic_cache()
        assert store._topic_cache is not None
        path = store.cfg.sources_path / "test.md"
        post = new_post("body", title="Test")
        store.write_note(path, post)
        assert store._topic_cache is not None

    def test_load_cache_corrupt_file_skipped(self, store):
        td = store.cfg.topics_path
        cat = td / "AI技术"
        cat.mkdir()
        (cat / "good.md").write_text("---\ntitle: Good\n---\nbody\n", encoding="utf-8")
        (cat / "bad.md").write_bytes(b"\x00\x01\x80\x81\xfe\xff")
        cache = store._load_topic_cache()
        titles = [t for _, _, t, _ in cache]
        assert "Good" in titles

    def test_no_topics_dir_returns_empty(self, store):
        shutil.rmtree(store.cfg.topics_path)
        assert store._load_topic_cache() == []


class TestSearchTopicsEdgeCases:
    def test_short_query_words_skipped(self, store):
        td = store.cfg.topics_path
        cat = td / "AI技术"
        cat.mkdir()
        (cat / "a.md").write_text("---\ntitle: AI\n---\nbody\n", encoding="utf-8")
        assert store.search_topics("a") == []

    def test_tag_match_scores(self, store):
        _create_topic(store.cfg.topics_path, "a.md", title="X", tags=["deep-learning"], body="body")
        hits = store.search_topics("deep-learning")
        assert len(hits) > 0

    def test_content_match_scores(self, store):
        _create_topic(store.cfg.topics_path, "a.md", title="Unrelated", body="This mentions quantum computing")
        hits = store.search_topics("quantum computing")
        assert len(hits) > 0

    def test_write_note_to_nonexistent_topics_parent(self, store):
        """Lines 285-292: write_note to path not under topics_path (except branch)."""
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
            external = Path(f.name)
        try:
            post = new_post("body", title="External")
            store.write_note(external, post)
            assert external.exists()
        finally:
            external.unlink(missing_ok=True)

