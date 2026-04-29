"""Note service: listing, filtering, pagination."""
from __future__ import annotations

from pathlib import Path

import frontmatter

from lifebook.config import KnowledgeConfig
from lifebook.notes import read_note, write_note
from lifebook.store import NoteStore


class NoteService:
    def __init__(self, cfg: KnowledgeConfig, store: NoteStore | None = None):
        self.cfg = cfg
        self._store = store or NoteStore(cfg)

    def list_notes(
        self,
        category: str | None = None,
        tag: str | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> dict:
        notes = []
        for md, meta, title, content in self._store._load_topic_cache():
            if category and meta.get("category") != category:
                continue
            if tag and tag not in (meta.get("tags") or []):
                continue
            notes.append({
                "path": str(md.relative_to(self.cfg.root)),
                "title": title,
                "category": meta.get("category", ""),
                "tags": meta.get("tags") or [],
                "created": meta.get("created", ""),
                "status": meta.get("status", "active"),
                "summary": content[:200].strip(),
            })

        total = len(notes)
        start = (page - 1) * per_page
        items = notes[start:start + per_page]
        return {"items": items, "total": total, "page": page, "per_page": per_page}

    def get_note(self, rel_path: str) -> dict | None:
        path = self.cfg.root / rel_path
        if not path.is_file():
            return None
        try:
            post = read_note(path)
        except (FileNotFoundError, UnicodeDecodeError, ValueError):
            return None
        return {
            "path": rel_path,
            "title": post.get("title") or path.stem,
            "category": post.get("category", ""),
            "tags": post.get("tags") or [],
            "created": post.get("created", ""),
            "body": post.content,
            "metadata": dict(post.metadata),
        }

    def update_note(self, rel_path: str, updates: dict) -> dict | None:
        path = self.cfg.root / rel_path
        if not path.is_file():
            return None
        post = read_note(path)
        if "title" in updates and updates["title"] is not None:
            post["title"] = updates["title"]
        if "tags" in updates and updates["tags"] is not None:
            post["tags"] = updates["tags"]
        if "category" in updates and updates["category"] is not None:
            post["category"] = updates["category"]
        if "body" in updates and updates["body"] is not None:
            post.content = updates["body"]
        write_note(path, post)
        return self.get_note(rel_path)

    def get_categories(self) -> list[str]:
        return self._store.existing_categories()

    def get_tags(self) -> list[str]:
        tags: set[str] = set()
        for _md, meta, _title, _content in self._store._load_topic_cache():
            for t in meta.get("tags") or []:
                tags.add(t)
        return sorted(tags)
