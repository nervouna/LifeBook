"""System API endpoints."""
from fastapi import APIRouter

router = APIRouter()


@router.get("/doctor")
async def doctor() -> dict[str, list[dict]]:
    return {"checks": []}
