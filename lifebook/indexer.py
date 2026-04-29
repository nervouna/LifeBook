"""Incremental indexer: background thread that keeps vector index in sync."""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

from .config import Config
from .notes import read_note
from .vector import VectorIndex

logger = logging.getLogger(__name__)


class Indexer:
    """Watches topic notes and incrementally updates the vector index.

    Two trigger modes:
    1. Timer: runs incremental_update() every `interval` seconds (default 300).
    2. Manual: call incremental_update() directly (e.g., from a slash command).
    """

    META_FILENAME = "vector_meta.json"

    def __init__(self, cfg: Config, interval: int = 300):
        self.cfg = cfg
        self.interval = interval
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

        # Paths
        self.topics_path = cfg.knowledge.topics_path
        self.meta_path = cfg.knowledge.state_path / self.META_FILENAME
        self.persist_dir = cfg.knowledge.vector_store_path

        # Lazy-init vector index (heavy: loads model)
        self._index: VectorIndex | None = None

    @property
    def index(self) -> VectorIndex:
        """Lazy-load vector index on first access."""
        if self._index is None:
            self._index = VectorIndex(self.persist_dir)
        return self._index

    # ---------- public API ----------

    def start(self) -> None:
        """Start the background indexing thread."""
        if self._thread is not None and self._thread.is_alive():
            logger.warning("Indexer thread already running")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="lifebook-indexer",
            daemon=True,
        )
        self._thread.start()
        logger.info("Indexer started (interval=%ds)", self.interval)

    def stop(self) -> None:
        """Signal the background thread to stop."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=10)
            logger.info("Indexer stopped")

    def incremental_update(self) -> dict[str, int]:
        """Scan topic notes and upsert/delete changes.

        Returns:
            Dict with keys: upserted, deleted, unchanged, errors.
        """
        stats = {"upserted": 0, "deleted": 0, "unchanged": 0, "errors": 0}

        if not self.topics_path.exists():
            logger.warning("Topics path does not exist: %s", self.topics_path)
            return stats

        # Load previous index state
        meta = self._load_meta()
        indexed: dict[str, float] = meta.get("indexed", {})

        # Scan current files
        current_files: dict[str, Path] = {}
        for md in self.topics_path.rglob("*.md"):
            rel = str(md.relative_to(self.cfg.knowledge.root))
            current_files[rel] = md

        # Upsert new or modified files
        for rel, md_path in current_files.items():
            try:
                mtime = md_path.stat().st_mtime
                if rel in indexed and indexed[rel] == mtime:
                    stats["unchanged"] += 1
                    continue
                # Read and index
                text, metadata = self._extract_doc(md_path)
                if not text:
                    stats["unchanged"] += 1
                    continue
                self.index.upsert(doc_id=rel, text=text, metadata=metadata)
                indexed[rel] = mtime
                stats["upserted"] += 1
            except Exception as e:
                logger.warning("Failed to index %s: %s", rel, e)
                stats["errors"] += 1

        # Delete removed files
        stale_ids = set(indexed.keys()) - set(current_files.keys())
        for doc_id in stale_ids:
            try:
                self.index.delete(doc_id)
                del indexed[doc_id]
                stats["deleted"] += 1
            except Exception as e:
                logger.warning("Failed to delete %s: %s", doc_id, e)
                stats["errors"] += 1

        # Save updated meta
        meta["indexed"] = indexed
        self._save_meta(meta)

        logger.info(
            "Index update complete: upserted=%d deleted=%d unchanged=%d errors=%d",
            stats["upserted"], stats["deleted"],
            stats["unchanged"], stats["errors"],
        )
        return stats

    def full_rebuild(self) -> dict[str, int]:
        """Drop all indexed state and rebuild from scratch.

        Returns:
            Same stats dict as incremental_update().
        """
        logger.info("Full rebuild requested — clearing meta and re-indexing")
        self._save_meta({"indexed": {}})
        return self.incremental_update()

    # ---------- internals ----------

    def _run_loop(self) -> None:
        """Background loop: run incremental_update() periodically."""
        # Run immediately on start
        try:
            self.incremental_update()
        except Exception:
            logger.exception("Initial index update failed")

        while not self._stop_event.is_set():
            self._stop_event.wait(timeout=self.interval)
            if self._stop_event.is_set():
                break
            try:
                self.incremental_update()
            except Exception:
                logger.exception("Periodic index update failed")

    def _extract_doc(self, md_path: Path) -> tuple[str, dict[str, str]]:
        """Extract indexable text and metadata from a topic note.

        Returns:
            (text_to_embed, metadata_dict). text may be empty if note
            has no useful content (e.g., status != active).
        """
        post = read_note(md_path)

        # Only index active notes
        status = post.get("status", "")
        if status and status != "active":
            return "", {}

        title = post.get("title", md_path.stem) or md_path.stem
        category = post.get("category", "") or ""
        tags = post.get("tags", []) or []
        keywords = post.get("related_keywords", []) or []
        summary = post.get("summary", "") or ""

        # Build text to embed: title + summary + key_points + body
        parts = [title]
        if summary:
            parts.append(summary)
        key_points = post.get("key_points", []) or []
        if key_points:
            parts.append(" ".join(key_points))
        body = post.content.strip()
        if body:
            parts.append(body)

        text = "\n".join(parts)

        # ChromaDB metadata must be str/int/float — no lists
        metadata = {
            "title": title,
            "category": category,
            "tags": ",".join(tags) if tags else "",
            "related_keywords": ",".join(keywords) if keywords else "",
        }

        return text, metadata

    def _load_meta(self) -> dict[str, Any]:
        """Load index metadata from disk."""
        if not self.meta_path.exists():
            return {"indexed": {}}
        try:
            return json.loads(self.meta_path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("Failed to load meta %s: %s", self.meta_path, e)
            return {"indexed": {}}

    def _save_meta(self, meta: dict[str, Any]) -> None:
        """Save index metadata to disk."""
        self.meta_path.parent.mkdir(parents=True, exist_ok=True)
        self.meta_path.write_text(
            json.dumps(meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
