"""Markdown note I/O: read/write with YAML frontmatter."""
from __future__ import annotations

import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import frontmatter

CN_TZ = timezone(timedelta(hours=8))


def now_iso() -> str:
    return datetime.now(CN_TZ).replace(microsecond=0).isoformat()


def now_ts_compact() -> str:
    return datetime.now(CN_TZ).strftime("%Y%m%d-%H%M%S")


# ASCII filesystem reserved + common CJK fullwidth equivalents that either
# cause issues on some filesystems or simply look awkward in filenames.
# Keeping these in sync with wikilink_text() below is essential — any char
# transformed here must be transformed the same way when we write [[...]].
_fs_reserved = re.compile(r'[/\\:*?"<>|：？｜＜＞＊／＼\x00-\x1f]+')


def slugify(text: str, max_len: int = 60) -> str:
    """Produce a filesystem-safe name, preserving spaces/punctuation/CJK.

    Only replaces characters that are actually reserved on macOS/Linux/Windows
    filesystems (plus their CJK fullwidth equivalents). This keeps filenames
    readable and lets Obsidian's wikilinks resolve them by name without
    aliases in the common case.
    """
    if not text:
        return "untitled"
    s = text.strip()
    s = _fs_reserved.sub("-", s)
    # Collapse multiple separators and trim leading/trailing noise
    s = re.sub(r"\s+", " ", s).strip()
    s = s.strip(" .-")
    if len(s) > max_len:
        s = s[:max_len].rstrip(" .-")
    return s or "untitled"


def wikilink_text(title: str) -> str:
    """Normalize a note title for use inside [[...]] wikilinks.

    Must apply the exact same transformation as slugify() so that the text
    inside [[...]] resolves to the file on disk whose stem was produced by
    slugify(title). Any divergence between these two functions will cause
    broken wikilinks in Obsidian.
    """
    return slugify(title)


# Obsidian tag syntax: letters (incl. CJK), digits, underscore, hyphen.
# Everything else is invalid and causes "invalid tag name" warnings.
_tag_illegal = re.compile(r"[^\w\u4e00-\u9fff\-]+", re.UNICODE)


def sanitize_tag(tag: str) -> str:
    """Clean a tag to comply with Obsidian syntax.

    - Replaces illegal chars (spaces, dots, punctuation, etc.) with hyphens.
    - Collapses runs of hyphens/underscores.
    - Strips leading/trailing separators.
    - Returns empty string if nothing usable remains (caller should filter).
    """
    if not tag:
        return ""
    s = tag.strip().lstrip("#")
    s = _tag_illegal.sub("-", s)
    s = re.sub(r"-+", "-", s).strip("-_")
    return s


def sanitize_tags(tags: list[str]) -> list[str]:
    """Apply sanitize_tag to a list, dropping empties and dedup-preserving order."""
    seen: set[str] = set()
    out: list[str] = []
    for t in tags or []:
        clean = sanitize_tag(t)
        if not clean or clean in seen:
            continue
        seen.add(clean)
        out.append(clean)
    return out


def read_note(path: Path) -> frontmatter.Post:
    with path.open("r", encoding="utf-8") as f:
        return frontmatter.load(f)


def write_note(path: Path, post: frontmatter.Post) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        f.write(frontmatter.dumps(post, sort_keys=False))
        f.write("\n")


def new_post(body: str, **meta: Any) -> frontmatter.Post:
    post = frontmatter.Post(body)
    for k, v in meta.items():
        post[k] = v
    return post


def unique_path(directory: Path, stem: str, suffix: str = ".md") -> Path:
    """Return a path that doesn't collide; append -2, -3, ... if needed."""
    directory.mkdir(parents=True, exist_ok=True)
    p = directory / f"{stem}{suffix}"
    i = 2
    while p.exists():
        p = directory / f"{stem}-{i}{suffix}"
        i += 1
    return p
