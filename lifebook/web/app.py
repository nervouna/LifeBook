"""FastAPI application factory."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..config import Config


def create_app(cfg: Config) -> FastAPI:
    app = FastAPI(title="LifeBook", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.cfg = cfg
    app.state.vector_index = None

    from ..llm import LLMClient
    app.state.llm_client = LLMClient(cfg.llm)

    from .api import api_router
    app.include_router(api_router, prefix="/api")

    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        from fastapi.responses import FileResponse

        @app.get("/{path:path}")
        async def serve_spa(path: str) -> FileResponse:
            file = static_dir / path
            if file.is_file():
                return FileResponse(file)
            return FileResponse(static_dir / "index.html")

    return app
