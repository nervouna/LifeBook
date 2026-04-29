"""Search service: semantic search orchestration."""
from __future__ import annotations

from lifebook.vector import VectorIndex


class SearchService:
    def __init__(self, vector_index: VectorIndex):
        self._vi = vector_index

    def search(self, query: str, limit: int = 10) -> list[dict]:
        if not query.strip():
            return []
        results = self._vi.search(query, n_results=limit)
        items = []
        for r in results:
            items.append({
                "path": r.doc_id,
                "title": r.metadata.get("title", r.doc_id),
                "score": max(0, 1.0 - r.distance),
                "preview": r.text[:200],
            })
        return items
