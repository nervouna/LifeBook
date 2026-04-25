"""Inbox API endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Request

from ..schemas import InboxListResponse, InboxIngestRequest
from ..services.inbox_service import InboxService

router = APIRouter()


def _svc(request: Request) -> InboxService:
    return InboxService(request.app.state.cfg)


@router.get("", response_model=InboxListResponse)
def list_inbox(request: Request, status: str | None = None):
    return _svc(request).list_inbox(status=status)


@router.post("")
def ingest(req: InboxIngestRequest, request: Request):
    return _svc(request).ingest(req.url_or_text, source_type=req.source_type, title=req.title)
