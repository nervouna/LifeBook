"""FastAPI application factory."""
from __future__ import annotations

from pathlib import Path
from typing import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

from ..config import Config

_EXEMPT_PATHS = frozenset({"/api/system/doctor"})


class PathTraversalMiddleware(BaseHTTPMiddleware):
    """Reject requests with '..' path segments before routing."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # Check both the normalized scope path and the raw_path (ASGI)
        for path in (
            request.scope.get("raw_path", b"").decode(errors="replace"),
            request.scope.get("path", ""),
        ):
            if any(p == ".." for p in path.split("/")):
                return Response(
                    content='{"detail":"Invalid path"}',
                    status_code=400,
                    media_type="application/json",
                )
        return await call_next(request)


class APIKeyMiddleware(BaseHTTPMiddleware):
    """Verify X-API-Key header on /api/ routes when api_key is configured."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        cfg: Config = request.app.state.cfg
        if cfg.web.api_key and request.url.path.startswith("/api"):
            if request.url.path not in _EXEMPT_PATHS:
                key = request.headers.get("X-API-Key")
                if key != cfg.web.api_key:
                    return Response(
                        content='{"detail":"Invalid or missing API key"}',
                        status_code=401,
                        media_type="application/json",
                    )
        return await call_next(request)


def create_app(cfg: Config) -> FastAPI:
    app = FastAPI(title="LifeBook", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.web.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(APIKeyMiddleware)
    app.add_middleware(PathTraversalMiddleware)
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
