"""System API endpoints."""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/doctor")
async def doctor() -> dict[str, list]:
    return {"checks": []}
