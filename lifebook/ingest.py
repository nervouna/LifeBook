"""Helper to create inbox files from URLs or raw text."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal

from .config import KnowledgeConfig
from .notes import new_post, now_iso, now_ts_compact, slugify, unique_path, write_note


SourceType = Literal["webclip", "chat_link", "chat_note", "manual", "trending"]


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


def ingest_image(
    knowledge: KnowledgeConfig,
    image_bytes: bytes,
    mime_type: str,
    title_hint: str | None = None,
    caption: str | None = None,
) -> Path:
    """Save image bytes to the images store and create an inbox source record.

    The raw image is written to ``{sources_path}/images/<hash>.<ext>`` and the
    source note's ``image_path`` metadata field points to that file (relative
    to ``knowledge.root``).  A SHA-256 content hash is stored for dedup.
    """
    ext = _ext_for_mime(mime_type)
    img_hash = hashlib.sha256(image_bytes).hexdigest()

    images_dir = knowledge.sources_path / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    img_path = images_dir / f"{img_hash}{ext}"
    if not img_path.exists():
        img_path.write_bytes(image_bytes)

    rel_path = str(img_path.relative_to(knowledge.root))

    stem_base = slugify(title_hint or "image", max_len=30)
    stem = f"img-{now_ts_compact()}-{stem_base}"
    note_path = unique_path(knowledge.sources_path, stem)

    meta: dict = {
        "created": now_iso(),
        "source_type": "image",
        "status": "inbox",
        "image_path": rel_path,
        "image_hash": img_hash,
        "image_mime": mime_type,
    }
    if title_hint:
        meta["title"] = title_hint
    content = caption.strip() if caption else ""
    write_note(note_path, new_post(content, **meta))
    return note_path


def _ext_for_mime(mime_type: str) -> str:
    return {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
        "image/webp": ".webp",
    }.get(mime_type.lower(), ".bin")
