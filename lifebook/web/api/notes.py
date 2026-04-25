"""Note API endpoints."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from ..schemas import NoteListResponse, NoteDetail, NoteUpdate
from ..services.note_service import NoteService

router = APIRouter()


def _svc(request: Request) -> NoteService:
    return NoteService(request.app.state.cfg.knowledge)


@router.get("", response_model=NoteListResponse)
def list_notes(
    request: Request,
    category: str | None = None,
    tag: str | None = None,
    page: int = 1,
    per_page: int = 20,
):
    return _svc(request).list_notes(category=category, tag=tag, page=page, per_page=per_page)


@router.get("/{path:path}", response_model=NoteDetail)
def get_note(path: str, request: Request):
    note = _svc(request).get_note(path)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    return note


@router.put("/{path:path}", response_model=NoteDetail)
def update_note(path: str, update: NoteUpdate, request: Request):
    svc = _svc(request)
    note = svc.update_note(path, update.model_dump(exclude_none=True))
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    return note


@router.delete("/{path:path}")
def delete_note(path: str, request: Request):
    from pathlib import Path
    cfg = request.app.state.cfg.knowledge
    full = cfg.root / path
    if not full.is_file():
        raise HTTPException(status_code=404, detail="Note not found")
    full.unlink()
    return {"ok": True}
