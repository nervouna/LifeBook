"""Inbox API endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

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


@router.post("/process-all")
async def process_all_inbox_items(request: Request):
    svc = _svc(request)
    return EventSourceResponse(svc.process_all())


@router.post("/{path:path}/process")
async def process_inbox_item(path: str, request: Request):
    svc = _svc(request)
    return EventSourceResponse(svc.process_single(path))
