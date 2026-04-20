"""Coverage tests for notes.py missing lines."""
from __future__ import annotations

from pathlib import Path

from lifebook.notes import (
    now_ts_compact,
    slugify,
    wikilink_text,
    sanitize_tag,
    sanitize_tags,
    read_note,
    write_note,
    unique_path,
    new_post,
)


class TestNowTsCompact:
    def test_returns_string(self):
        result = now_ts_compact()
        assert isinstance(result, str)
        assert "-" in result


class TestSlugify:
    def test_empty_returns_untitled(self):
        assert slugify("") == "untitled"

    def test_truncates_long(self):
        long = "a" * 100
        result = slugify(long, max_len=10)
        assert len(result) <= 10

    def test_strips_dots_dashes(self):
        result = slugify("...hello...")
        assert result == "hello"

    def test_reserved_chars_replaced(self):
        result = slugify("file/name\\test:what")
        assert "/" not in result
        assert "\\" not in result

    def test_only_reserved_returns_untitled(self):
        assert slugify("///") == "untitled"


class TestWikilinkText:
    def test_delegates_to_slugify(self):
        assert wikilink_text("Hello/World") == slugify("Hello/World")


class TestSanitizeTag:
    def test_empty(self):
        assert sanitize_tag("") == ""

    def test_strips_hash(self):
        assert sanitize_tag("#tag") == "tag"

    def test_replaces_spaces(self):
        assert sanitize_tag("my tag") == "my-tag"

    def test_collapses_hyphens(self):
        assert sanitize_tag("a--b") == "a-b"


class TestSanitizeTags:
    def test_deduplicates(self):
        result = sanitize_tags(["tag1", "tag1", "tag2"])
        assert result == ["tag1", "tag2"]

    def test_drops_empty(self):
        result = sanitize_tags(["", "valid"])
        assert result == ["valid"]

    def test_none_input(self):
        result = sanitize_tags(None)
        assert result == []


class TestUniquePath:
    def test_creates_unique(self, tmp_path: Path):
        p1 = unique_path(tmp_path, "test")
        p1.write_text("x")
        p2 = unique_path(tmp_path, "test")
        assert p2.name == "test-2.md"

    def test_creates_parent(self, tmp_path: Path):
        sub = tmp_path / "sub"
        p = unique_path(sub, "test")
        assert sub.exists()


class TestReadNote:
    def test_roundtrip(self, tmp_path: Path):
        p = tmp_path / "test.md"
        post = new_post("body", title="T")
        write_note(p, post)
        loaded = read_note(p)
        assert loaded.get("title") == "T"
        assert loaded.content == "body"
