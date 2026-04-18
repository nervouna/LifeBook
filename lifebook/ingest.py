"""Helper to create inbox files from URLs or raw text."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from .config import KnowledgeConfig
from .notes import new_post, now_iso, now_ts_compact, slugify, unique_path, write_note


SourceType = Literal["webclip", "chat_link", "chat_note", "manual"]


def ingest_url(
    knowledge: KnowledgeConfig,
    url: str,
    source_type: SourceType = "chat_link",
    title_hint: str | None = None,
) -> Path:
    """Create an inbox record for a URL; content will be fetched at process time."""
    stem_base = slugify(title_hint or url.split("/")[-1] or "link", max_len=30)
    stem = f"{{prefix}}-{now_ts_compact()}-{stem_base}".format(
        prefix={"webclip": "web", "chat_link": "link", "chat_note": "note", "manual": "man"}[source_type]
    )
    path = unique_path(knowledge.sources_path, stem)
    meta = {
        "created": now_iso(),
        "source": url,
        "source_type": source_type,
        "status": "inbox",
    }
    if title_hint:
        meta["title"] = title_hint
    write_note(path, new_post("", **meta))
    return path


def ingest_text(
    knowledge: KnowledgeConfig,
    text: str,
    source_type: SourceType = "chat_note",
    title_hint: str | None = None,
) -> Path:
    stem_base = slugify(title_hint or text[:30] or "note", max_len=30)
    stem = f"note-{now_ts_compact()}-{stem_base}"
    path = unique_path(knowledge.sources_path, stem)
    meta = {
        "created": now_iso(),
        "source_type": source_type,
        "status": "inbox",
    }
    if title_hint:
        meta["title"] = title_hint
    write_note(path, new_post(text.strip(), **meta))
    return path
