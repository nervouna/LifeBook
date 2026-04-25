"""Inbox service: listing, ingest, process orchestration."""
from __future__ import annotations

from lifebook.config import Config
from lifebook.notes import read_note


class InboxService:
    def __init__(self, cfg: Config):
        self.cfg = cfg

    def list_inbox(self, status: str | None = None) -> dict:
        sources_path = self.cfg.knowledge.sources_path
        if not sources_path.exists():
            return {"items": [], "total": 0}

        items = []
        for md in sorted(sources_path.glob("*.md")):
            try:
                post = read_note(md)
            except Exception:
                continue
            s = post.get("status", "inbox")
            if status:
                if s != status:
                    continue
            elif s != "inbox":
                continue
            items.append({
                "path": str(md.relative_to(self.cfg.knowledge.root)),
                "title": post.get("title") or md.stem,
                "status": s,
                "source_type": post.get("source_type", "manual"),
                "source": post.get("source", ""),
                "created": post.get("created", ""),
                "error": post.get("fetch_error"),
            })
        return {"items": items, "total": len(items)}

    def ingest(self, url_or_text: str, source_type: str = "manual", title: str | None = None) -> dict:
        from lifebook.ingest import ingest_url, ingest_text

        is_url = url_or_text.startswith("http://") or url_or_text.startswith("https://")
        if is_url:
            path = ingest_url(self.cfg.knowledge, url_or_text, source_type=source_type, title_hint=title)
        else:
            path = ingest_text(self.cfg.knowledge, url_or_text, source_type=source_type, title_hint=title)
        return {"path": str(path.relative_to(self.cfg.knowledge.root))}
