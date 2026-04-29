"""Search API endpoint."""
from __future__ import annotations

from fastapi import APIRouter, Request

from ..schemas import SearchRequest, SearchResponse
from ..services.search_service import SearchService

router = APIRouter()


def _get_vector_index(request: Request):
    vi = request.app.state.vector_index
    if vi is None:
        from lifebook.vector import VectorIndex
        vi = VectorIndex(request.app.state.cfg.knowledge.vector_store_path)
        request.app.state.vector_index = vi
    return vi


@router.post("", response_model=SearchResponse)
def search(req: SearchRequest, request: Request):
    svc = SearchService(_get_vector_index(request))
    results = svc.search(req.query, limit=req.limit)
    return {"results": results, "query": req.query}
