"""Podcast API endpoints."""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from ...tts import TTSError
from ..schemas import PodcastGenerateRequest, PodcastGenerateMultiRequest

router = APIRouter()
logger = logging.getLogger(__name__)


def _classify_error(e: Exception) -> tuple[str, str]:
    """Classify exception into error code and user-friendly message."""
    if isinstance(e, FileNotFoundError):
        return "NOT_FOUND", "笔记文件不存在"
    if isinstance(e, ValueError):
        return "INVALID_INPUT", str(e)
    if isinstance(e, TTSError):
        logger.warning("TTS error: %s", e)
        return "TTS_ERROR", "语音合成失败，请稍后重试"
    logger.exception("Podcast generation error")
    return "INTERNAL_ERROR", "播客生成失败，请稍后重试"


@router.post("/generate")
async def generate_podcast(req: PodcastGenerateRequest, request: Request):
    cfg = request.app.state.cfg
    note_path = cfg.knowledge.root / req.note_path
    if not note_path.is_file():
        raise HTTPException(status_code=404, detail="Note not found")

    from lifebook.llm import LLMClient
    from lifebook.podcast import PodcastGenerator

    gen = PodcastGenerator(cfg, llm=LLMClient(cfg.llm))

    async def event_stream():
        yield {"event": "progress", "data": json.dumps({"step": "script", "message": "生成播客脚本..."})}
        try:
            audio_bytes, duration = gen.generate(note_path)
            output = note_path.with_name(f"{note_path.stem}_podcast.mp3")
            output.write_bytes(audio_bytes)
            yield {"event": "done", "data": json.dumps({"path": output.name, "duration": duration})}
        except Exception as e:
            code, msg = _classify_error(e)
            yield {"event": "error", "data": json.dumps({"code": code, "message": msg})}

    return EventSourceResponse(event_stream())


@router.post("/generate-multi")
async def generate_podcast_multi(req: PodcastGenerateMultiRequest, request: Request):
    cfg = request.app.state.cfg
    import datetime as dt

    from lifebook.podcast import select_notes, PodcastGenerator
    from lifebook.llm import LLMClient

    since_date = dt.date.fromisoformat(req.since)
    notes, total = select_notes(cfg.knowledge.topics_path, since_date, req.limit)
    if not notes:
        raise HTTPException(status_code=404, detail="No notes found")

    gen = PodcastGenerator(cfg, llm=LLMClient(cfg.llm))
    has_more = total > req.limit

    async def event_stream():
        yield {
            "event": "progress",
            "data": json.dumps({
                "step": "script",
                "message": f"生成合集脚本（{len(notes)}/{total} 篇笔记）...",
            }),
        }
        try:
            audio_bytes, duration = gen.generate_multi(notes, has_more)
            date_str = since_date.isoformat()
            output = cfg.knowledge.topics_path / f"podcast_{date_str}_multi.mp3"
            output.write_bytes(audio_bytes)
            yield {
                "event": "done",
                "data": json.dumps({
                    "path": output.name,
                    "duration": duration,
                    "notes_used": len(notes),
                    "notes_total": total,
                }),
            }
        except Exception as e:
            code, msg = _classify_error(e)
            yield {"event": "error", "data": json.dumps({"code": code, "message": msg})}

    return EventSourceResponse(event_stream())
