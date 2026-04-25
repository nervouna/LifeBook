"""Search API endpoint."""
from __future__ import annotations

from fastapi import APIRouter, Request

from ..schemas import SearchRequest, SearchResponse
from ..services.search_service import SearchService

router = APIRouter()


@router.post("", response_model=SearchResponse)
def search(req: SearchRequest, request: Request):
    svc = SearchService(request.app.state.cfg.knowledge)
    results = svc.search(req.query, limit=req.limit)
    return {"results": results, "query": req.query}
