"""System API endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Request

from ..schemas import StatsResponse, DoctorResponse, CategoryListResponse, TagListResponse
from ..services.note_service import NoteService
from ..services.inbox_service import InboxService

router = APIRouter()


@router.get("/doctor", response_model=DoctorResponse)
def doctor(request: Request):
    cfg = request.app.state.cfg
    checks = [
        {"name": "Knowledge root", "ok": cfg.knowledge.root.exists()},
        {"name": "Topics dir", "ok": cfg.knowledge.topics_path.exists()},
        {"name": "Sources dir", "ok": cfg.knowledge.sources_path.exists()},
        {"name": "LLM API key", "ok": bool(cfg.llm.api_key)},
    ]
    return {"checks": checks}


@router.get("/stats", response_model=StatsResponse)
def stats(request: Request):
    cfg = request.app.state.cfg
    from lifebook.store import NoteStore
    note_svc = NoteService(cfg.knowledge)
    inbox_svc = InboxService(cfg)
    store = NoteStore(cfg.knowledge)
    return {
        "topic_count": store.topic_count(),
        "inbox_count": inbox_svc.list_inbox(status="inbox")["total"],
        "categories": note_svc.get_categories(),
        "index_status": "ok" if cfg.knowledge.vector_store_path.exists() else "not_indexed",
    }


@router.post("/index")
def rebuild_index(request: Request, full: bool = False):
    cfg = request.app.state.cfg
    from lifebook.indexer import Indexer
    indexer = Indexer(cfg)
    if full:
        stats = indexer.full_rebuild()
    else:
        stats = indexer.incremental_update()
    return stats


@router.get("/categories", response_model=CategoryListResponse)
def list_categories(request: Request):
    svc = NoteService(request.app.state.cfg.knowledge)
    return {"categories": svc.get_categories()}


@router.get("/tags", response_model=TagListResponse)
def list_tags(request: Request):
    svc = NoteService(request.app.state.cfg.knowledge)
    return {"tags": svc.get_tags()}
