"""Writer API endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Request

from ..schemas import WriterStatus, WriterStartRequest, WriterChatRequest, WriterChatResponse
from ..services.writer_service import WriterService

router = APIRouter()


def _svc(request: Request) -> WriterService:
    return WriterService(request.app.state.cfg)


@router.get("/status", response_model=WriterStatus)
def writer_status(request: Request):
    return _svc(request).get_status()


@router.post("/start", response_model=WriterChatResponse)
def writer_start(req: WriterStartRequest, request: Request):
    return _svc(request).start(req.idea)


@router.post("/chat", response_model=WriterChatResponse)
def writer_chat(req: WriterChatRequest, request: Request):
    return _svc(request).chat(req.message)


@router.post("/publish")
def writer_publish(request: Request, force: bool = False):
    return _svc(request).publish(force=force)


@router.post("/restore")
def writer_restore(request: Request):
    return _svc(request).restore()
