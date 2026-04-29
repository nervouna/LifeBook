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
    _check_path(path, request)
    note = _svc(request).get_note(path)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    return note


@router.put("/{path:path}", response_model=NoteDetail)
def update_note(path: str, update: NoteUpdate, request: Request):
    _check_path(path, request)
    svc = _svc(request)
    note = svc.update_note(path, update.model_dump(exclude_none=True))
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    return note


@router.delete("/{path:path}")
def delete_note(path: str, request: Request):
    _check_path(path, request)
    cfg = request.app.state.cfg.knowledge
    full = cfg.root / path
    if not full.is_file():
        raise HTTPException(status_code=404, detail="Note not found")
    full.unlink()
    return {"ok": True}


def _check_path(path: str, request: Request) -> None:
    """Reject path traversal attempts."""
    from pathlib import PurePosixPath
    parts = PurePosixPath(path).parts
    if any(p == ".." for p in parts):
        raise HTTPException(status_code=400, detail="Invalid path")
    cfg = request.app.state.cfg.knowledge
    resolved = (cfg.root / path).resolve()
    if not resolved.is_relative_to(cfg.root.resolve()):
        raise HTTPException(status_code=400, detail="Invalid path")
