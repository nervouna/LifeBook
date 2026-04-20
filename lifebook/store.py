"""NoteStore: centralized filesystem access for the knowledge base."""
from __future__ import annotations

import fcntl
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import frontmatter

from .config import KnowledgeConfig
from .notes import (
    CN_TZ,
    now_iso,
    read_note,
    slugify,
    write_note,
)

logger = logging.getLogger(__name__)


@dataclass
class TopicHit:
    """A search result from topic notes."""
    score: float
    title: str
    summary: str
    path: Path


class NoteStore:
    """Centralizes all filesystem access to the knowledge base.

    Provides a single place for: inbox scanning, file locking, topic search,
    related-note discovery, and generic note I/O.
    """

    def __init__(self, cfg: KnowledgeConfig):
        self.cfg = cfg
        self._topic_cache: list[tuple[Path, dict, str, str]] | None = None

    # ---------- source (inbox) operations ----------

    def scan_inbox(self) -> list[Path]:
        """List all source files with status: inbox."""
        root = self.cfg.sources_path
        if not root.exists():
            return []
        out = []
        for p in sorted(root.glob("*.md")):
            try:
                post = read_note(p)
            except Exception as e:
                logger.warning("skip unreadable %s: %s", p, e)
                continue
            if post.get("status") == "inbox":
                out.append(p)
        return out

    def claim_for_processing(self, source_path: Path) -> tuple[bool, frontmatter.Post]:
        """Atomically claim a source file: flip status inbox -> processing.

        Returns (claimed, post). Uses fcntl.flock on a .lock sidecar file.
        """
        lock_path = source_path.with_suffix(source_path.suffix + ".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with open(lock_path, "w", encoding="utf-8") as lock_fh:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX)
            try:
                post = read_note(source_path)
                if post.get("status") != "inbox":
                    return False, post
                post["status"] = "processing"
                post["processing_at"] = now_iso()
                write_note(source_path, post)
                return True, post
            finally:
                fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)

    def recover_stale(
        self, timeout_minutes: int = 10, dry_run: bool = False,
    ) -> list[tuple[Path, str]]:
        """Roll back files stuck in status:processing for longer than timeout."""
        root = self.cfg.sources_path
        if not root.exists():
            return []
        now = datetime.now(CN_TZ)
        stale: list[tuple[Path, str]] = []
        for p in sorted(root.glob("*.md")):
            try:
                post = read_note(p)
            except Exception as e:
                logger.warning("skip unreadable %s: %s", p, e)
                continue
            if post.get("status") != "processing":
                continue
            pa = post.get("processing_at")
            if not pa:
                stale.append((p, "(no processing_at)"))
                if not dry_run:
                    post["status"] = "inbox"
                    post.metadata.pop("processing_at", None)
                    write_note(p, post)
                continue
            try:
                if isinstance(pa, datetime):
                    pa_dt = pa
                else:
                    pa_dt = datetime.fromisoformat(str(pa))
            except Exception:
                stale.append((p, f"(bad timestamp: {pa})"))
                if not dry_run:
                    post["status"] = "inbox"
                    post.metadata.pop("processing_at", None)
                    write_note(p, post)
                continue
            age_min = (now - pa_dt).total_seconds() / 60
            if age_min >= timeout_minutes:
                stale.append((p, f"{pa} ({age_min:.1f}min old)"))
                if not dry_run:
                    post["status"] = "inbox"
                    post.metadata.pop("processing_at", None)
                    write_note(p, post)
        return stale

    # ---------- topic operations ----------

    def existing_categories(self) -> list[str]:
        """List subdirectory names under topics_path."""
        root = self.cfg.topics_path
        if not root.exists():
            return []
        return sorted([
            d.name for d in root.iterdir()
            if d.is_dir() and not d.name.startswith(".")
        ])

    def find_by_source_url(self, url: str) -> Path | None:
        """Check if a topic note with this source_url already exists."""
        if not url:
            return None
        for path, meta, _title, _content in self._load_topic_cache():
            if meta.get("source_url") == url:
                return path
        return None

    def _load_topic_cache(self) -> list[tuple[Path, dict, str, str]]:
        """Load and cache topic notes metadata and content."""
        if self._topic_cache is not None:
            return self._topic_cache

        root = self.cfg.topics_path
        if not root.exists():
            self._topic_cache = []
            return self._topic_cache

        cache = []
        for md in root.rglob("*.md"):
            try:
                post = read_note(md)
                title = post.get("title") or md.stem
                # Store path, metadata dict, full title string, and content
                cache.append((md, post.metadata, title, post.content))
            except Exception:
                continue
        self._topic_cache = cache
        return cache

    def _invalidate_topic_cache(self) -> None:
        """Invalidate the topic cache (e.g., after a write)."""
        self._topic_cache = None

    def find_related(self, keywords: list[str], max_hits: int = 5) -> list[str]:
        """Scan topics/*/*.md; return titles whose title/tags/keywords match."""
        if not keywords:
            return []
        kw_lower = [k.lower() for k in keywords]
        hits: list[tuple[int, str]] = []

        cache = self._load_topic_cache()
        for _, metadata, title, _ in cache:
            haystack = " ".join([
                title,
                " ".join(metadata.get("tags") or []),
                " ".join(metadata.get("related_keywords") or []),
            ]).lower()
            score = sum(1 for k in kw_lower if k and k in haystack)
            if score > 0:
                hits.append((score, title))

        hits.sort(key=lambda x: (-x[0], x[1]))
        seen: set[str] = set()
        out: list[str] = []
        for _, t in hits:
            if t in seen:
                continue
            seen.add(t)
            out.append(t)
            if len(out) >= max_hits:
                break
        return out

    def find_by_title(self, title: str) -> Path | None:
        """Find a topic note by exact title or slugified stem. Returns path or None."""
        cache = self._load_topic_cache()
        for md, _, cached_title, _ in cache:
            if cached_title == title or md.stem == slugify(title):
                return md
        return None

    def topic_count(self) -> int:
        """Count all .md files under topics_path."""
        cache = self._load_topic_cache()
        return len(cache)

    # ---------- search (unified) ----------

    def search_topics(self, query: str, max_notes: int = 5) -> list[TopicHit]:
        """Search topics using category/tag structured filtering + keyword matching.

        Returns sorted list of TopicHit (highest score first).
        """
        query_lower = query.lower()
        words = [w for w in query_lower.split() if len(w) >= 2]
        if not words:
            return []

        hits: list[TopicHit] = []
        cache = self._load_topic_cache()
        for md, metadata, title, content in cache:
            category = (metadata.get("category") or "").lower()
            tags = [t.lower() for t in (metadata.get("tags") or [])]

            # Layer 1: structured match (category + tags)
            struct_score = 0.0
            for w in words:
                if w in category:
                    struct_score += 3.0
                for tag in tags:
                    if w in tag:
                        struct_score += 2.0
                        break

            # Layer 2: keyword match on title + content
            title_lower = title.lower()
            content_lower = content[:500].lower()
            keyword_score = 0.0
            for w in words:
                if w in title_lower:
                    keyword_score += 2.0
                elif w in content_lower:
                    keyword_score += 1.0

            total = struct_score + keyword_score
            if total > 0:
                summary = content[:200].strip()
                hits.append(TopicHit(score=total, title=title, summary=summary, path=md))

        hits.sort(key=lambda x: -x.score)
        return hits[:max_notes]

    def search_topics_formatted(self, query: str, max_notes: int = 5) -> str:
        """Search topics and return formatted string for LLM context."""
        hits = self.search_topics(query, max_notes)
        if not hits:
            return ""
        parts = []
        for hit in hits:
            parts.append(f"### {hit.title}\n{hit.summary}\n")
        return "\n".join(parts)

    # ---------- generic note I/O (delegates to notes.py) ----------

    def read_note(self, path: Path) -> frontmatter.Post:
        return read_note(path)

    def write_note(self, path: Path, post: frontmatter.Post) -> None:
        write_note(path, post)
        # Invalidate cache only if writing to topics directory
        try:
            if path.is_relative_to(self.cfg.topics_path):
                self._invalidate_topic_cache()
        except (AttributeError, ValueError):
            # Fallback for older Python versions or relative path issues
            # If path starts with topics_path, invalidate
            try:
                path.relative_to(self.cfg.topics_path)
                self._invalidate_topic_cache()
            except ValueError:
                pass
