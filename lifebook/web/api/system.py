"""System API endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Request

from ..schemas import CategoryListResponse, TagListResponse
from ..services.note_service import NoteService

router = APIRouter()


@router.get("/doctor")
async def doctor() -> dict[str, list]:
    return {"checks": []}


@router.get("/categories", response_model=CategoryListResponse)
def list_categories(request: Request):
    svc = NoteService(request.app.state.cfg.knowledge)
    return {"categories": svc.get_categories()}


@router.get("/tags", response_model=TagListResponse)
def list_tags(request: Request):
    svc = NoteService(request.app.state.cfg.knowledge)
    return {"tags": svc.get_tags()}
