"""API router aggregation."""
from __future__ import annotations

from fastapi import APIRouter

from .notes import router as notes_router
from .inbox import router as inbox_router
from .search import router as search_router
from .writer import router as writer_router
from .podcast import router as podcast_router
from .system import router as system_router

api_router = APIRouter()
api_router.include_router(notes_router, prefix="/notes", tags=["notes"])
api_router.include_router(inbox_router, prefix="/inbox", tags=["inbox"])
api_router.include_router(search_router, prefix="/search", tags=["search"])
api_router.include_router(writer_router, prefix="/writer", tags=["writer"])
api_router.include_router(podcast_router, prefix="/podcast", tags=["podcast"])
api_router.include_router(system_router, prefix="/system", tags=["system"])
