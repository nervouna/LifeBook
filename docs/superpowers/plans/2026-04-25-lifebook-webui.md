# LifeBook WebUI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a web-based workbench to LifeBook for browsing notes, managing inbox, semantic search, and interactive writing agent.

**Architecture:** FastAPI serves REST API + SSE endpoints, with a service layer handling web-specific logic (pagination, filtering, aggregation). React SPA (Vite + Tailwind + shadcn/ui) served as static files from the same process.

**Tech Stack:** Python 3.10+, FastAPI, uvicorn, sse-starlette, Pydantic v2, React 18, TypeScript, Vite, Tailwind CSS, shadcn/ui, TanStack Query

---

## File Structure

### Backend (new files)

| File | Responsibility |
|------|----------------|
| `lifebook/web/__init__.py` | Package init |
| `lifebook/web/app.py` | FastAPI app factory, mount static files, CORS |
| `lifebook/web/api/__init__.py` | Router aggregation |
| `lifebook/web/api/notes.py` | Note CRUD + listing endpoints |
| `lifebook/web/api/inbox.py` | Inbox listing + processing endpoints (SSE) |
| `lifebook/web/api/search.py` | Semantic search endpoint |
| `lifebook/web/api/writer.py` | Writing agent chat endpoints (SSE) |
| `lifebook/web/api/podcast.py` | Podcast generation endpoints (SSE) |
| `lifebook/web/api/system.py` | Doctor, stats, index, categories, tags |
| `lifebook/web/schemas.py` | Pydantic request/response models |
| `lifebook/web/services/__init__.py` | Package init |
| `lifebook/web/services/note_service.py` | Note listing, filtering, pagination |
| `lifebook/web/services/inbox_service.py` | Inbox operations, process orchestration |
| `lifebook/web/services/search_service.py` | Search orchestration |
| `lifebook/web/services/writer_service.py` | Writer state + chat orchestration |
| `tests/web/__init__.py` | Test package |
| `tests/web/conftest.py` | Shared fixtures (mock config, test client) |
| `tests/web/test_api_notes.py` | Note API tests |
| `tests/web/test_api_inbox.py` | Inbox API tests |
| `tests/web/test_api_search.py` | Search API tests |
| `tests/web/test_api_writer.py` | Writer API tests |
| `tests/web/test_api_system.py` | System API tests |

### Backend (modified files)

| File | Change |
|------|--------|
| `lifebook/config.py` | Add `WebConfig` dataclass, add to `Config` |
| `lifebook/cli.py` | Add `web` command |
| `pyproject.toml` | Add fastapi, uvicorn, sse-starlette deps |

### Frontend (new directory)

| Path | Responsibility |
|------|----------------|
| `frontend/package.json` | Dependencies |
| `frontend/vite.config.ts` | Vite config, proxy /api to backend |
| `frontend/tsconfig.json` | TypeScript config |
| `frontend/tailwind.config.ts` | Tailwind config |
| `frontend/index.html` | Entry HTML |
| `frontend/src/main.tsx` | React entry point |
| `frontend/src/App.tsx` | Router + layout |
| `frontend/src/lib/api.ts` | API client (fetch wrapper) |
| `frontend/src/hooks/` | TanStack Query hooks |
| `frontend/src/components/` | Shared UI components |
| `frontend/src/pages/` | Page components (Dashboard, Notes, Inbox, Search, Writer, Podcast) |

---

## Task 1: Backend Scaffolding — Config + Dependencies + CLI

**Files:**
- Modify: `lifebook/config.py`
- Modify: `pyproject.toml`
- Modify: `lifebook/cli.py`
- Create: `lifebook/web/__init__.py`
- Create: `lifebook/web/app.py`
- Test: `tests/web/__init__.py`, `tests/web/conftest.py`, `tests/web/test_app.py`

- [ ] **Step 1: Add WebConfig to config.py**

Add after `LoggingConfig` (line ~148):

```python
@dataclass
class WebConfig:
    host: str = "127.0.0.1"
    port: int = 8080
    debug: bool = False
```

Add `web: WebConfig = field(default_factory=WebConfig)` to the `Config` dataclass (after `feishu_podcast`).

In `load_config()`, add before the `return Config(...)`:
```python
web = WebConfig(**_filter(WebConfig, raw.get("web")))
```

And add `web=web` to the `Config(...)` constructor call.

- [ ] **Step 2: Add dependencies to pyproject.toml**

Add to `dependencies` list:
```
"fastapi>=0.115.0",
"uvicorn[standard]>=0.30.0",
"sse-starlette>=2.0.0",
```

- [ ] **Step 3: Create lifebook/web/__init__.py**

```python
"""LifeBook web interface."""
```

- [ ] **Step 4: Create lifebook/web/app.py**

```python
"""FastAPI application factory."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

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
```

- [ ] **Step 5: Create lifebook/web/api/__init__.py**

```python
"""API router aggregation."""
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
api_router.include_router(system_router, tags=["system"])  # /categories, /tags
```

- [ ] **Step 6: Create stub route files**

Each of `notes.py`, `inbox.py`, `search.py`, `writer.py`, `podcast.py`, `system.py` should contain a minimal router. Example for `notes.py`:

```python
"""Note API endpoints."""
from fastapi import APIRouter

router = APIRouter()
```

Repeat for all six files with appropriate docstrings.

- [ ] **Step 7: Add `web` CLI command to cli.py**

Add after the `serve` command:

```python
@main.command()
@click.option("--host", default=None, help="Bind host (default: from config).")
@click.option("--port", type=int, default=None, help="Bind port (default: from config).")
@click.option("--reload", "do_reload", is_flag=True, default=False, help="Enable auto-reload for development.")
@click.pass_context
def web(ctx: click.Context, host: str | None, port: int | None, do_reload: bool) -> None:
    """Start the web interface."""
    import uvicorn
    from .web.app import create_app
    cfg = ctx.obj["config"]
    app = create_app(cfg)
    uvicorn.run(
        app,
        host=host or cfg.web.host,
        port=port or cfg.web.port,
        reload=do_reload,
    )
```

- [ ] **Step 8: Create test fixtures**

`tests/web/__init__.py`: empty file.

`tests/web/conftest.py`:
```python
"""Shared fixtures for web API tests."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from lifebook.config import Config, KnowledgeConfig, LLMConfig, WebConfig
from lifebook.web.app import create_app


@pytest.fixture
def mock_config(tmp_path: Path) -> Config:
    sources = tmp_path / "10-sources"
    sources.mkdir()
    topics = tmp_path / "20-topics"
    topics.mkdir()
    publish = tmp_path / "99-publish"
    publish.mkdir()
    state = tmp_path / ".lifebook"
    state.mkdir()

    return Config(
        knowledge=KnowledgeConfig(root=tmp_path),
        llm=LLMConfig(),
        feishu=MagicMock(),
        executor=MagicMock(),
        digest=MagicMock(),
        tavily=MagicMock(),
        fetch=MagicMock(),
        logging=MagicMock(),
        web=WebConfig(),
    )


@pytest.fixture
def client(mock_config: Config) -> TestClient:
    app = create_app(mock_config)
    return TestClient(app)
```

- [ ] **Step 9: Write test for app creation**

`tests/web/test_app.py`:
```python
"""Tests for web app factory."""
from fastapi.testclient import TestClient


def test_app_creates(client: TestClient):
    response = client.get("/api/system/doctor")
    assert response.status_code == 200


def test_api_prefix(client: TestClient):
    response = client.get("/api/notes")
    assert response.status_code == 200
```

- [ ] **Step 10: Run tests and verify**

Run: `python -m pytest tests/web/ -v`
Expected: PASS (stubs return appropriate responses)

- [ ] **Step 11: Commit**

```bash
git add lifebook/config.py lifebook/cli.py lifebook/web/ pyproject.toml tests/web/
git commit -m "feat: add web scaffolding with FastAPI app factory and CLI command"
```

---

## Task 2: Pydantic Schemas

**Files:**
- Create: `lifebook/web/schemas.py`
- Test: `tests/web/test_schemas.py`

- [ ] **Step 1: Write failing test**

`tests/web/test_schemas.py`:
```python
"""Tests for web schemas."""
from __future__ import annotations

from lifebook.web.schemas import (
    NoteListItem,
    NoteDetail,
    InboxItem,
    SearchResultItem,
    WriterStatus,
    WriterChatRequest,
    StatsResponse,
)


def test_note_list_item():
    item = NoteListItem(path="20-topics/AI技术/Test.md", title="Test", category="AI技术", tags=["tag1"], created="2026-01-01", status="active")
    assert item.title == "Test"


def test_note_detail():
    detail = NoteDetail(path="20-topics/AI技术/Test.md", title="Test", category="AI技术", tags=[], created="2026-01-01", body="content", metadata={})
    assert detail.body == "content"


def test_inbox_item():
    item = InboxItem(path="10-sources/test.md", title="Test", status="inbox", source_type="manual", created="2026-01-01")
    assert item.status == "inbox"


def test_search_result_item():
    item = SearchResultItem(path="20-topics/AI技术/Test.md", title="Test", score=0.95, preview="text...")
    assert item.score == 0.95


def test_writer_status():
    status = WriterStatus(active=True, stage="concept", title="My Article")
    assert status.active is True


def test_writer_chat_request():
    req = WriterChatRequest(message="hello")
    assert req.message == "hello"


def test_stats_response():
    stats = StatsResponse(topic_count=10, inbox_count=3, categories=["AI技术"])
    assert stats.topic_count == 10
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/web/test_schemas.py -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Write schemas.py**

`lifebook/web/schemas.py`:
```python
"""Pydantic request/response models for the web API."""
from __future__ import annotations

from pydantic import BaseModel, Field


class NoteListItem(BaseModel):
    path: str
    title: str
    category: str = ""
    tags: list[str] = Field(default_factory=list)
    created: str = ""
    status: str = "active"
    summary: str = ""


class NoteDetail(BaseModel):
    path: str
    title: str
    category: str = ""
    tags: list[str] = Field(default_factory=list)
    created: str = ""
    body: str = ""
    metadata: dict = Field(default_factory=dict)


class NoteUpdate(BaseModel):
    title: str | None = None
    tags: list[str] | None = None
    category: str | None = None
    body: str | None = None


class NoteListResponse(BaseModel):
    items: list[NoteListItem]
    total: int
    page: int
    per_page: int


class InboxItem(BaseModel):
    path: str
    title: str = ""
    status: str = "inbox"
    source_type: str = "manual"
    source: str = ""
    created: str = ""
    error: str | None = None


class InboxListResponse(BaseModel):
    items: list[InboxItem]
    total: int


class InboxIngestRequest(BaseModel):
    url_or_text: str
    source_type: str = "manual"
    title: str | None = None


class SearchResultItem(BaseModel):
    path: str
    title: str
    score: float
    preview: str = ""


class SearchRequest(BaseModel):
    query: str
    limit: int = 10


class SearchResponse(BaseModel):
    results: list[SearchResultItem]
    query: str


class WriterStatus(BaseModel):
    active: bool
    stage: str | None = None
    title: str | None = None


class WriterStartRequest(BaseModel):
    idea: str


class WriterChatRequest(BaseModel):
    message: str


class WriterChatResponse(BaseModel):
    reply: str
    stage: str | None = None


class PodcastGenerateRequest(BaseModel):
    note_path: str


class PodcastGenerateMultiRequest(BaseModel):
    since: str
    limit: int = 10


class StatsResponse(BaseModel):
    topic_count: int
    inbox_count: int
    categories: list[str]
    index_status: str = "unknown"


class DoctorResponse(BaseModel):
    checks: list[dict]
    config_source: str = ""


class CategoryListResponse(BaseModel):
    categories: list[str]


class TagListResponse(BaseModel):
    tags: list[str]


class ErrorResponse(BaseModel):
    error: str
    detail: str | None = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/web/test_schemas.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add lifebook/web/schemas.py tests/web/test_schemas.py
git commit -m "feat: add Pydantic schemas for web API"
```

---

## Task 3: Note Service + API

**Files:**
- Create: `lifebook/web/services/__init__.py`
- Create: `lifebook/web/services/note_service.py`
- Modify: `lifebook/web/api/notes.py`
- Test: `tests/web/test_api_notes.py`

- [ ] **Step 1: Write failing test**

`tests/web/test_api_notes.py`:
```python
"""Tests for note API endpoints."""
from __future__ import annotations

from pathlib import Path

import frontmatter
import pytest


def _write_topic(topics_dir: Path, category: str, filename: str, title: str, body: str = "content", **meta):
    d = topics_dir / category
    d.mkdir(parents=True, exist_ok=True)
    path = d / filename
    post = frontmatter.Post(body)
    post["title"] = title
    post["category"] = category
    post["created"] = "2026-01-01T00:00:00+08:00"
    for k, v in meta.items():
        post[k] = v
    path.write_text(frontmatter.dumps(post, sort_keys=False), encoding="utf-8")
    return path


class TestListNotes:
    def test_empty(self, client):
        resp = client.get("/api/notes")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["items"] == []

    def test_lists_notes(self, client, mock_config):
        _write_topic(mock_config.knowledge.topics_path, "AI技术", "Test-Note.md", "Test Note")
        resp = client.get("/api/notes")
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["title"] == "Test Note"

    def test_filter_by_category(self, client, mock_config):
        _write_topic(mock_config.knowledge.topics_path, "AI技术", "A.md", "Note A")
        _write_topic(mock_config.knowledge.topics_path, "半导体", "B.md", "Note B")
        resp = client.get("/api/notes", params={"category": "AI技术"})
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["category"] == "AI技术"

    def test_pagination(self, client, mock_config):
        for i in range(5):
            _write_topic(mock_config.knowledge.topics_path, "AI技术", f"Note-{i}.md", f"Note {i}")
        resp = client.get("/api/notes", params={"page": 1, "per_page": 2})
        data = resp.json()
        assert len(data["items"]) == 2
        assert data["total"] == 5


class TestGetNote:
    def test_returns_detail(self, client, mock_config):
        path = _write_topic(mock_config.knowledge.topics_path, "AI技术", "Test.md", "Test Note", "body content")
        rel = str(path.relative_to(mock_config.knowledge.root))
        resp = client.get(f"/api/notes/{rel}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "Test Note"
        assert data["body"] == "body content"

    def test_not_found(self, client):
        resp = client.get("/api/notes/20-topics/AI技术/Nonexistent.md")
        assert resp.status_code == 404


class TestUpdateNote:
    def test_updates_tags(self, client, mock_config):
        path = _write_topic(mock_config.knowledge.topics_path, "AI技术", "Test.md", "Test Note")
        rel = str(path.relative_to(mock_config.knowledge.root))
        resp = client.put(f"/api/notes/{rel}", json={"tags": ["new-tag"]})
        assert resp.status_code == 200
        data = resp.json()
        assert "new-tag" in data["metadata"]["tags"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/web/test_api_notes.py -v`
Expected: FAIL (endpoints not implemented)

- [ ] **Step 3: Create services/__init__.py**

```python
"""Web service layer."""
```

- [ ] **Step 4: Create note_service.py**

`lifebook/web/services/note_service.py`:
```python
"""Note service: listing, filtering, pagination."""
from __future__ import annotations

from pathlib import Path

import frontmatter

from lifebook.config import KnowledgeConfig
from lifebook.notes import read_note, write_note


class NoteService:
    def __init__(self, cfg: KnowledgeConfig):
        self.cfg = cfg

    def list_notes(
        self,
        category: str | None = None,
        tag: str | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> dict:
        notes = []
        topics_path = self.cfg.topics_path
        if not topics_path.exists():
            return {"items": [], "total": 0, "page": page, "per_page": per_page}

        for md in sorted(topics_path.rglob("*.md")):
            try:
                post = read_note(md)
            except Exception:
                continue
            meta = post.metadata
            if category and meta.get("category") != category:
                continue
            if tag and tag not in (meta.get("tags") or []):
                continue
            notes.append({
                "path": str(md.relative_to(self.cfg.root)),
                "title": meta.get("title") or md.stem,
                "category": meta.get("category", ""),
                "tags": meta.get("tags") or [],
                "created": meta.get("created", ""),
                "status": meta.get("status", "active"),
                "summary": post.content[:200].strip(),
            })

        total = len(notes)
        start = (page - 1) * per_page
        items = notes[start:start + per_page]
        return {"items": items, "total": total, "page": page, "per_page": per_page}

    def get_note(self, rel_path: str) -> dict | None:
        path = self.cfg.root / rel_path
        if not path.is_file():
            return None
        try:
            post = read_note(path)
        except Exception:
            return None
        return {
            "path": rel_path,
            "title": post.get("title") or path.stem,
            "category": post.get("category", ""),
            "tags": post.get("tags") or [],
            "created": post.get("created", ""),
            "body": post.content,
            "metadata": dict(post.metadata),
        }

    def update_note(self, rel_path: str, updates: dict) -> dict | None:
        path = self.cfg.root / rel_path
        if not path.is_file():
            return None
        post = read_note(path)
        if "title" in updates and updates["title"] is not None:
            post["title"] = updates["title"]
        if "tags" in updates and updates["tags"] is not None:
            post["tags"] = updates["tags"]
        if "category" in updates and updates["category"] is not None:
            post["category"] = updates["category"]
        if "body" in updates and updates["body"] is not None:
            post.content = updates["body"]
        write_note(path, post)
        return self.get_note(rel_path)

    def get_categories(self) -> list[str]:
        topics_path = self.cfg.topics_path
        if not topics_path.exists():
            return []
        return sorted(d.name for d in topics_path.iterdir() if d.is_dir() and not d.name.startswith("."))

    def get_tags(self) -> list[str]:
        tags: set[str] = set()
        topics_path = self.cfg.topics_path
        if not topics_path.exists():
            return []
        for md in topics_path.rglob("*.md"):
            try:
                post = read_note(md)
                for t in post.get("tags") or []:
                    tags.add(t)
            except Exception:
                continue
        return sorted(tags)
```

- [ ] **Step 5: Implement notes API**

`lifebook/web/api/notes.py`:
```python
"""Note API endpoints."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from ..schemas import NoteListResponse, NoteDetail, NoteUpdate, CategoryListResponse, TagListResponse
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
    note = _svc(request).get_note(path)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    return note


@router.put("/{path:path}", response_model=NoteDetail)
def update_note(path: str, update: NoteUpdate, request: Request):
    svc = _svc(request)
    note = svc.update_note(path, update.model_dump(exclude_none=True))
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    return note


@router.delete("/{path:path}")
def delete_note(path: str, request: Request):
    from pathlib import Path
    cfg = request.app.state.cfg.knowledge
    full = cfg.root / path
    if not full.is_file():
        raise HTTPException(status_code=404, detail="Note not found")
    full.unlink()
    return {"ok": True}
```

Also add categories and tags to `system.py`:

```python
"""System API endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Request

from ..schemas import CategoryListResponse, TagListResponse
from ..services.note_service import NoteService

router = APIRouter()


@router.get("/categories", response_model=CategoryListResponse)
def list_categories(request: Request):
    svc = NoteService(request.app.state.cfg.knowledge)
    return {"categories": svc.get_categories()}


@router.get("/tags", response_model=TagListResponse)
def list_tags(request: Request):
    svc = NoteService(request.app.state.cfg.knowledge)
    return {"tags": svc.get_tags()}
```

- [ ] **Step 6: Run tests**

Run: `python -m pytest tests/web/test_api_notes.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add lifebook/web/services/__init__.py lifebook/web/services/note_service.py lifebook/web/api/notes.py lifebook/web/api/system.py tests/web/test_api_notes.py
git commit -m "feat: add note service and API with listing, filtering, pagination"
```

---

## Task 4: Inbox Service + API

**Files:**
- Create: `lifebook/web/services/inbox_service.py`
- Modify: `lifebook/web/api/inbox.py`
- Test: `tests/web/test_api_inbox.py`

- [ ] **Step 1: Write failing test**

`tests/web/test_api_inbox.py`:
```python
"""Tests for inbox API endpoints."""
from __future__ import annotations

from pathlib import Path

import pytest


def _write_source(sources_dir: Path, filename: str, status: str = "inbox", source_type: str = "manual", **meta):
    path = sources_dir / filename
    lines = ["---"]
    lines.append(f"status: {status}")
    lines.append(f"source_type: {source_type}")
    lines.append(f"created: '2026-01-01T00:00:00+08:00'")
    for k, v in meta.items():
        lines.append(f"{k}: {v}")
    lines.append("---")
    lines.append("Some content")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class TestListInbox:
    def test_empty(self, client):
        resp = client.get("/api/inbox")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0

    def test_lists_inbox(self, client, mock_config):
        _write_source(mock_config.knowledge.sources_path, "a.md")
        _write_source(mock_config.knowledge.sources_path, "b.md", status="processed")
        resp = client.get("/api/inbox")
        data = resp.json()
        assert data["total"] == 1

    def test_filter_by_status(self, client, mock_config):
        _write_source(mock_config.knowledge.sources_path, "a.md", status="inbox")
        _write_source(mock_config.knowledge.sources_path, "b.md", status="processing")
        resp = client.get("/api/inbox", params={"status": "inbox"})
        data = resp.json()
        assert data["total"] == 1


class TestIngest:
    def test_ingest_text(self, client, mock_config):
        resp = client.post("/api/inbox", json={"url_or_text": "test content"})
        assert resp.status_code == 200
        data = resp.json()
        assert "path" in data
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/web/test_api_inbox.py -v`
Expected: FAIL

- [ ] **Step 3: Create inbox_service.py**

`lifebook/web/services/inbox_service.py`:
```python
"""Inbox service: listing, ingest, process orchestration."""
from __future__ import annotations

from pathlib import Path

from lifebook.config import Config
from lifebook.notes import read_note


class InboxService:
    def __init__(self, cfg: Config):
        self.cfg = cfg

    def list_inbox(self, status: str | None = None) -> dict:
        sources_path = self.cfg.knowledge.sources_path
        if not sources_path.exists():
            return {"items": [], "total": 0}

        items = []
        for md in sorted(sources_path.glob("*.md")):
            try:
                post = read_note(md)
            except Exception:
                continue
            s = post.get("status", "inbox")
            if status and s != status:
                continue
            items.append({
                "path": str(md.relative_to(self.cfg.knowledge.root)),
                "title": post.get("title") or md.stem,
                "status": s,
                "source_type": post.get("source_type", "manual"),
                "source": post.get("source", ""),
                "created": post.get("created", ""),
                "error": post.get("fetch_error"),
            })
        return {"items": items, "total": len(items)}

    def ingest(self, url_or_text: str, source_type: str = "manual", title: str | None = None) -> dict:
        from lifebook.ingest import ingest_url, ingest_text
        is_url = url_or_text.startswith("http://") or url_or_text.startswith("https://")
        if is_url:
            path = ingest_url(self.cfg.knowledge, url_or_text, source_type=source_type, title_hint=title)
        else:
            path = ingest_text(self.cfg.knowledge, url_or_text, source_type=source_type, title_hint=title)
        return {"path": str(path.relative_to(self.cfg.knowledge.root))}
```

- [ ] **Step 4: Implement inbox API**

`lifebook/web/api/inbox.py`:
```python
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
```

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/web/test_api_inbox.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add lifebook/web/services/inbox_service.py lifebook/web/api/inbox.py tests/web/test_api_inbox.py
git commit -m "feat: add inbox service and API with listing and ingest"
```

---

## Task 5: Search API

**Files:**
- Create: `lifebook/web/services/search_service.py`
- Modify: `lifebook/web/api/search.py`
- Test: `tests/web/test_api_search.py`

- [ ] **Step 1: Write failing test**

`tests/web/test_api_search.py`:
```python
"""Tests for search API endpoint."""
from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest


class TestSearch:
    def test_empty_query(self, client):
        resp = client.post("/api/search", json={"query": "", "limit": 10})
        assert resp.status_code == 200
        data = resp.json()
        assert data["results"] == []

    @patch("lifebook.web.services.search_service.VectorIndex")
    def test_returns_results(self, mock_vi_cls, client):
        mock_vi = MagicMock()
        mock_result = MagicMock()
        mock_result.doc_id = "20-topics/AI技术/Test.md"
        mock_result.distance = 0.1
        mock_result.metadata = {"title": "Test Note"}
        mock_result.text = "Some preview text"
        mock_vi.search.return_value = [mock_result]
        mock_vi_cls.return_value = mock_vi

        resp = client.post("/api/search", json={"query": "test", "limit": 10})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["results"]) == 1
        assert data["results"][0]["title"] == "Test Note"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/web/test_api_search.py -v`
Expected: FAIL

- [ ] **Step 3: Create search_service.py**

`lifebook/web/services/search_service.py`:
```python
"""Search service: semantic search orchestration."""
from __future__ import annotations

from lifebook.config import KnowledgeConfig


class SearchService:
    def __init__(self, cfg: KnowledgeConfig):
        self.cfg = cfg

    def search(self, query: str, limit: int = 10) -> list[dict]:
        if not query.strip():
            return []
        from lifebook.vector import VectorIndex
        vi = VectorIndex(self.cfg.vector_store_path)
        results = vi.search(query, n_results=limit)
        items = []
        for r in results:
            items.append({
                "path": r.doc_id,
                "title": r.metadata.get("title", r.doc_id),
                "score": max(0, 1.0 - r.distance),
                "preview": r.text[:200],
            })
        return items
```

- [ ] **Step 4: Implement search API**

`lifebook/web/api/search.py`:
```python
"""Search API endpoint."""
from __future__ import annotations

from fastapi import APIRouter, Request

from ..schemas import SearchRequest, SearchResponse
from ..services.search_service import SearchService

router = APIRouter()


@router.post("", response_model=SearchResponse)
def search(req: SearchRequest, request: Request):
    svc = SearchService(request.app.state.cfg.knowledge)
    results = svc.search(req.query, limit=req.limit)
    return {"results": results, "query": req.query}
```

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/web/test_api_search.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add lifebook/web/services/search_service.py lifebook/web/api/search.py tests/web/test_api_search.py
git commit -m "feat: add search service and API"
```

---

## Task 6: Writer Service + API

**Files:**
- Create: `lifebook/web/services/writer_service.py`
- Modify: `lifebook/web/api/writer.py`
- Test: `tests/web/test_api_writer.py`

- [ ] **Step 1: Write failing test**

`tests/web/test_api_writer.py`:
```python
"""Tests for writer API endpoints."""
from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest


class TestWriterStatus:
    @patch("lifebook.web.services.writer_service.LLMClient")
    def test_no_active_draft(self, mock_llm_cls, client, mock_config):
        resp = client.get("/api/writer/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["active"] is False

    @patch("lifebook.web.services.writer_service.LLMClient")
    def test_active_draft(self, mock_llm_cls, client, mock_config):
        draft_meta = mock_config.knowledge.publish_path / "draft.json"
        draft_meta.write_text('{"stage": "concept", "title": "Test"}', encoding="utf-8")
        resp = client.get("/api/writer/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["active"] is True
        assert data["stage"] == "concept"


class TestWriterStart:
    @patch("lifebook.web.services.writer_service.LLMClient")
    def test_start_session(self, mock_llm_cls, client, mock_config):
        mock_llm = MagicMock()
        mock_llm.structured_call.return_value = {
            "topic": "Test Topic",
            "thesis": "Test thesis",
            "audience": "General",
            "concept_text": "A concept",
        }
        mock_llm_cls.return_value = mock_llm
        resp = client.post("/api/writer/start", json={"idea": "write about AI"})
        assert resp.status_code == 200
        data = resp.json()
        assert "reply" in data


class TestWriterChat:
    @patch("lifebook.web.services.writer_service.LLMClient")
    def test_chat_without_active_session(self, mock_llm_cls, client, mock_config):
        resp = client.post("/api/writer/chat", json={"message": "hello"})
        assert resp.status_code == 200
        data = resp.json()
        assert "没有" in data["reply"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/web/test_api_writer.py -v`
Expected: FAIL

- [ ] **Step 3: Create writer_service.py**

`lifebook/web/services/writer_service.py`:
```python
"""Writer service: state management and chat orchestration."""
from __future__ import annotations

from lifebook.config import Config
from lifebook.llm import LLMClient
from lifebook.writer import Writer


class WriterService:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._writer: Writer | None = None

    def _get_writer(self) -> Writer:
        if self._writer is None:
            self._writer = Writer(self.cfg, LLMClient(self.cfg.llm))
        return self._writer

    def get_status(self) -> dict:
        w = self._get_writer()
        if not w.active:
            return {"active": False, "stage": None, "title": None}
        meta, _ = w._load_draft()
        return {
            "active": True,
            "stage": w.stage,
            "title": meta.get("title") if meta else None,
        }

    def start(self, idea: str) -> dict:
        w = self._get_writer()
        reply = w.start(idea)
        return {"reply": reply, "stage": w.stage}

    def chat(self, message: str) -> dict:
        w = self._get_writer()
        if not w.active:
            return {"reply": "当前没有进行中的写作。请先开始一个新的写作会话。", "stage": None}
        reply = w.handle_message(message)
        return {"reply": reply, "stage": w.stage}

    def publish(self, force: bool = False) -> dict:
        w = self._get_writer()
        reply = w.publish(force=force)
        self._writer = None
        return {"reply": reply}

    def restore(self) -> dict:
        w = self._get_writer()
        reply = w.restore_draft()
        return {"reply": reply}
```

- [ ] **Step 4: Implement writer API**

`lifebook/web/api/writer.py`:
```python
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
```

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/web/test_api_writer.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add lifebook/web/services/writer_service.py lifebook/web/api/writer.py tests/web/test_api_writer.py
git commit -m "feat: add writer service and API with status, start, chat, publish"
```

---

## Task 7: System API + Podcast API

**Files:**
- Modify: `lifebook/web/api/system.py`
- Modify: `lifebook/web/api/podcast.py`
- Test: `tests/web/test_api_system.py`

- [ ] **Step 1: Write failing test**

`tests/web/test_api_system.py`:
```python
"""Tests for system and podcast API endpoints."""
from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest


class TestSystemDoctor:
    def test_doctor(self, client):
        resp = client.get("/api/system/doctor")
        assert resp.status_code == 200
        data = resp.json()
        assert "checks" in data


class TestSystemStats:
    def test_stats(self, client, mock_config):
        resp = client.get("/api/system/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "topic_count" in data
        assert "inbox_count" in data
        assert "categories" in data


class TestCategories:
    def test_empty(self, client):
        resp = client.get("/api/categories")
        assert resp.status_code == 200

    def test_has_categories(self, client, mock_config):
        (mock_config.knowledge.topics_path / "AI技术").mkdir()
        resp = client.get("/api/categories")
        data = resp.json()
        assert "AI技术" in data["categories"]


class TestTags:
    def test_empty(self, client):
        resp = client.get("/api/tags")
        assert resp.status_code == 200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/web/test_api_system.py -v`
Expected: FAIL

- [ ] **Step 3: Complete system.py**

`lifebook/web/api/system.py`:
```python
"""System API endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Request

from ..schemas import StatsResponse, DoctorResponse, CategoryListResponse, TagListResponse
from ..services.note_service import NoteService
from ..services.inbox_service import InboxService

router = APIRouter()


@router.get("/doctor", response_model=DoctorResponse)
def doctor(request: Request):
    cfg = request.app.state.cfg
    checks = [
        {"name": "Knowledge root", "ok": cfg.knowledge.root.exists()},
        {"name": "Topics dir", "ok": cfg.knowledge.topics_path.exists()},
        {"name": "Sources dir", "ok": cfg.knowledge.sources_path.exists()},
        {"name": "LLM API key", "ok": bool(cfg.llm.api_key)},
    ]
    return {"checks": checks}


@router.get("/stats", response_model=StatsResponse)
def stats(request: Request):
    cfg = request.app.state.cfg
    note_svc = NoteService(cfg.knowledge)
    inbox_svc = InboxService(cfg)
    return {
        "topic_count": len(list(cfg.knowledge.topics_path.rglob("*.md"))) if cfg.knowledge.topics_path.exists() else 0,
        "inbox_count": inbox_svc.list_inbox(status="inbox")["total"],
        "categories": note_svc.get_categories(),
        "index_status": "ok" if cfg.knowledge.vector_store_path.exists() else "not_indexed",
    }


@router.post("/index")
def rebuild_index(request: Request, full: bool = False):
    cfg = request.app.state.cfg
    from lifebook.indexer import Indexer
    indexer = Indexer(cfg)
    if full:
        stats = indexer.full_rebuild()
    else:
        stats = indexer.incremental_update()
    return stats


@router.get("/categories", response_model=CategoryListResponse)
def list_categories(request: Request):
    svc = NoteService(request.app.state.cfg.knowledge)
    return {"categories": svc.get_categories()}


@router.get("/tags", response_model=TagListResponse)
def list_tags(request: Request):
    svc = NoteService(request.app.state.cfg.knowledge)
    return {"tags": svc.get_tags()}
```

- [ ] **Step 4: Implement podcast API**

`lifebook/web/api/podcast.py`:
```python
"""Podcast API endpoints."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from ..schemas import PodcastGenerateRequest, PodcastGenerateMultiRequest

router = APIRouter()


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
        yield {"event": "progress", "data": '{"step": "script", "message": "生成播客脚本..."}'}
        try:
            audio_bytes, duration = gen.generate(note_path)
            output = note_path.with_name(f"{note_path.stem}_podcast.mp3")
            output.write_bytes(audio_bytes)
            yield {"event": "done", "data": f'{{"path": "{output.name}", "duration": {duration}}}'}
        except Exception as e:
            yield {"event": "error", "data": f'{{"message": "{str(e)}"}'}

    return EventSourceResponse(event_stream())


@router.post("/generate-multi")
async def generate_podcast_multi(req: PodcastGenerateMultiRequest, request: Request):
    cfg = request.app.state.cfg
    import datetime as dt

    from lifebook.podcast import select_notes
    from lifebook.llm import LLMClient
    from lifebook.podcast import PodcastGenerator

    since_date = dt.date.fromisoformat(req.since)
    notes, total = select_notes(cfg.knowledge.topics_path, since_date, req.limit)
    if not notes:
        raise HTTPException(status_code=404, detail="No notes found")

    gen = PodcastGenerator(cfg, llm=LLMClient(cfg.llm))
    has_more = total > req.limit

    async def event_stream():
        yield {"event": "progress", "data": '{"step": "script", "message": "生成合集脚本..."}'}
        try:
            audio_bytes, duration = gen.generate_multi(notes, has_more)
            date_str = since_date.isoformat()
            output = cfg.knowledge.topics_path / f"podcast_{date_str}_multi.mp3"
            output.write_bytes(audio_bytes)
            yield {"event": "done", "data": f'{{"path": "{output.name}", "duration": {duration}}}'}
        except Exception as e:
            yield {"event": "error", "data": f'{{"message": "{str(e)}"}'}

    return EventSourceResponse(event_stream())
```

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/web/test_api_system.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add lifebook/web/api/system.py lifebook/web/api/podcast.py tests/web/test_api_system.py
git commit -m "feat: add system and podcast API endpoints"
```

---

## Task 8: Inbox Process SSE

**Files:**
- Modify: `lifebook/web/api/inbox.py`
- Modify: `lifebook/web/services/inbox_service.py`
- Test: `tests/web/test_api_inbox_process.py`

- [ ] **Step 1: Write failing test**

`tests/web/test_api_inbox_process.py`:
```python
"""Tests for inbox process SSE endpoints."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


def _write_source(sources_dir: Path, filename: str, status: str = "inbox"):
    path = sources_dir / filename
    lines = ["---", f"status: {status}", "source_type: manual", "created: '2026-01-01T00:00:00+08:00'", "---", "content"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class TestProcessSingle:
    @patch("lifebook.web.services.inbox_service.Executor")
    def test_process_file(self, mock_exec_cls, client, mock_config):
        _write_source(mock_config.knowledge.sources_path, "test.md")
        mock_exec = MagicMock()
        result = MagicMock()
        result.ok = True
        result.topic_path = mock_config.knowledge.topics_path / "AI技术" / "Test.md"
        result.skipped_reason = None
        result.error = None
        mock_exec.process_file.return_value = result
        mock_exec_cls.return_value = mock_exec

        with client.stream("POST", "/api/inbox/10-sources/test.md/process") as resp:
            assert resp.status_code == 200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/web/test_api_inbox_process.py -v`
Expected: FAIL

- [ ] **Step 3: Update inbox_service.py with process method**

Add to `InboxService`:
```python
    def process_single(self, rel_path: str):
        """Process a single inbox file. Yields SSE events."""
        from lifebook.executor import Executor
        executor = Executor(self.cfg)
        full_path = self.cfg.knowledge.root / rel_path
        if not full_path.is_file():
            yield {"event": "error", "data": '{"message": "File not found"}'}
            return
        yield {"event": "progress", "data": '{"step": "start", "message": "开始处理..."}'}
        result = executor.process_file(full_path)
        if result.ok:
            topic = str(result.topic_path.relative_to(self.cfg.knowledge.root)) if result.topic_path else ""
            yield {"event": "done", "data": f'{{"topic_path": "{topic}"}'}
        elif result.skipped_reason:
            yield {"event": "done", "data": f'{{"skipped": "{result.skipped_reason}"}'}
        else:
            yield {"event": "error", "data": f'{{"message": "{result.error}"}'}
```

- [ ] **Step 4: Add process endpoint to inbox.py**

Add to `lifebook/web/api/inbox.py`:
```python
from sse_starlette.sse import EventSourceResponse


@router.post("/{path:path}/process")
async def process_inbox_item(path: str, request: Request):
    svc = _svc(request)
    return EventSourceResponse(svc.process_single(path))
```

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/web/test_api_inbox_process.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add lifebook/web/api/inbox.py lifebook/web/services/inbox_service.py tests/web/test_api_inbox_process.py
git commit -m "feat: add inbox process SSE endpoint"
```

---

## Task 9: Frontend Scaffolding

**Files:**
- Create: `frontend/` directory with Vite + React + TypeScript + Tailwind + shadcn/ui

- [ ] **Step 1: Initialize Vite project**

Run:
```bash
cd /Users/damao/Projects/LifeBook
npm create vite@latest frontend -- --template react-ts
cd frontend
npm install
```

- [ ] **Step 2: Install Tailwind CSS**

Run:
```bash
cd /Users/damao/Projects/LifeBook/frontend
npm install -D tailwindcss @tailwindcss/vite
```

Update `vite.config.ts`:
```typescript
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8080",
    },
  },
  build: {
    outDir: "../lifebook/web/static",
    emptyOutDir: true,
  },
});
```

Replace `src/index.css` with:
```css
@import "tailwindcss";
```

- [ ] **Step 3: Install shadcn/ui and dependencies**

Run:
```bash
cd /Users/damao/Projects/LifeBook/frontend
npm install -D @types/node
npx shadcn@latest init
```

Select: New York style, Zinc base color, CSS variables: yes.

Install commonly used components:
```bash
npx shadcn@latest add button card input select table tabs badge dialog sheet scroll-area toast separator
```

- [ ] **Step 4: Install TanStack Query and React Router**

Run:
```bash
npm install @tanstack/react-query react-router-dom
```

- [ ] **Step 5: Create API client**

`frontend/src/lib/api.ts`:
```typescript
const BASE = "/api";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: res.statusText }));
    throw new Error(err.error || err.detail || res.statusText);
  }
  return res.json();
}

export const api = {
  // Notes
  listNotes: (params?: Record<string, string>) =>
    request<NoteListResponse>(`/notes?${new URLSearchParams(params || {})}`),
  getNote: (path: string) =>
    request<NoteDetail>(`/notes/${path}`),
  updateNote: (path: string, body: Partial<NoteUpdate>) =>
    request<NoteDetail>(`/notes/${path}`, { method: "PUT", body: JSON.stringify(body) }),
  deleteNote: (path: string) =>
    request<{ ok: boolean }>(`/notes/${path}`, { method: "DELETE" }),

  // Inbox
  listInbox: (params?: Record<string, string>) =>
    request<InboxListResponse>(`/inbox?${new URLSearchParams(params || {})}`),
  ingest: (body: { url_or_text: string; source_type?: string; title?: string }) =>
    request<{ path: string }>("/inbox", { method: "POST", body: JSON.stringify(body) }),

  // Search
  search: (query: string, limit = 10) =>
    request<SearchResponse>("/search", { method: "POST", body: JSON.stringify({ query, limit }) }),

  // Writer
  writerStatus: () => request<WriterStatus>("/writer/status"),
  writerStart: (idea: string) =>
    request<WriterChatResponse>("/writer/start", { method: "POST", body: JSON.stringify({ idea }) }),
  writerChat: (message: string) =>
    request<WriterChatResponse>("/writer/chat", { method: "POST", body: JSON.stringify({ message }) }),
  writerPublish: (force = false) =>
    request<{ reply: string }>(`/writer/publish?force=${force}`, { method: "POST" }),

  // System
  doctor: () => request<DoctorResponse>("/system/doctor"),
  stats: () => request<StatsResponse>("/system/stats"),
  categories: () => request<CategoryListResponse>("/categories"),
  tags: () => request<TagListResponse>("/tags"),

  // Podcast
  generatePodcast: (notePath: string) =>
    request<{ path: string }>("/podcast/generate", { method: "POST", body: JSON.stringify({ note_path: notePath }) }),
};

// Types
export type NoteListItem = { path: string; title: string; category: string; tags: string[]; created: string; status: string; summary: string };
export type NoteListResponse = { items: NoteListItem[]; total: number; page: number; per_page: number };
export type NoteDetail = { path: string; title: string; category: string; tags: string[]; created: string; body: string; metadata: Record<string, unknown> };
export type NoteUpdate = { title?: string; tags?: string[]; category?: string; body?: string };
export type InboxItem = { path: string; title: string; status: string; source_type: string; source: string; created: string; error: string | null };
export type InboxListResponse = { items: InboxItem[]; total: number };
export type SearchResultItem = { path: string; title: string; score: number; preview: string };
export type SearchResponse = { results: SearchResultItem[]; query: string };
export type WriterStatus = { active: boolean; stage: string | null; title: string | null };
export type WriterChatResponse = { reply: string; stage: string | null };
export type DoctorResponse = { checks: { name: string; ok: boolean }[] };
export type StatsResponse = { topic_count: number; inbox_count: number; categories: string[]; index_status: string };
export type CategoryListResponse = { categories: string[] };
export type TagListResponse = { tags: string[] };
```

- [ ] **Step 6: Create App layout with router**

`frontend/src/App.tsx`:
```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Routes, Route, NavLink } from "react-router-dom";
import { ScrollArea } from "@/components/ui/scroll-area";
import DashboardPage from "@/pages/Dashboard";
import NotesPage from "@/pages/Notes";
import InboxPage from "@/pages/Inbox";
import SearchPage from "@/pages/Search";
import WriterPage from "@/pages/Writer";
import PodcastPage from "@/pages/Podcast";

const queryClient = new QueryClient();

const navItems = [
  { to: "/", label: "概览", icon: "📊" },
  { to: "/inbox", label: "收件箱", icon: "📥" },
  { to: "/notes", label: "笔记", icon: "📝" },
  { to: "/writer", label: "写作", icon: "✍️" },
  { to: "/search", label: "搜索", icon: "🔍" },
  { to: "/podcast", label: "播客", icon: "🎙️" },
];

function Layout() {
  return (
    <div className="flex h-screen">
      <aside className="w-48 border-r bg-muted/40 flex flex-col">
        <div className="p-4 font-bold text-lg">LifeBook</div>
        <ScrollArea className="flex-1">
          <nav className="space-y-1 p-2">
            {navItems.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === "/"}
                className={({ isActive }) =>
                  `flex items-center gap-2 rounded-md px-3 py-2 text-sm transition-colors ${
                    isActive ? "bg-primary text-primary-foreground" : "hover:bg-muted"
                  }`
                }
              >
                <span>{item.icon}</span>
                <span>{item.label}</span>
              </NavLink>
            ))}
          </nav>
        </ScrollArea>
      </aside>
      <main className="flex-1 overflow-auto">
        <Routes>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/notes/*" element={<NotesPage />} />
          <Route path="/inbox" element={<InboxPage />} />
          <Route path="/search" element={<SearchPage />} />
          <Route path="/writer" element={<WriterPage />} />
          <Route path="/podcast" element={<PodcastPage />} />
        </Routes>
      </main>
    </div>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Layout />
      </BrowserRouter>
    </QueryClientProvider>
  );
}
```

- [ ] **Step 7: Create stub pages**

Create `frontend/src/pages/Dashboard.tsx`, `Notes.tsx`, `Inbox.tsx`, `Search.tsx`, `Writer.tsx`, `Podcast.tsx` — each a minimal component:

```tsx
export default function DashboardPage() {
  return <div className="p-6"><h1 className="text-2xl font-bold">概览</h1><p className="text-muted-foreground mt-2">Dashboard coming soon</p></div>;
}
```

Repeat pattern for each page with appropriate title.

- [ ] **Step 8: Update main.tsx**

`frontend/src/main.tsx`:
```tsx
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./index.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>
);
```

- [ ] **Step 9: Verify build**

Run:
```bash
cd /Users/damao/Projects/LifeBook/frontend
npm run build
ls ../lifebook/web/static/
```

Expected: `index.html`, `assets/` directory with JS/CSS bundles.

- [ ] **Step 10: Commit**

```bash
git add frontend/ lifebook/web/static/
git commit -m "feat: add frontend scaffolding with Vite, React, Tailwind, shadcn/ui"
```

---

## Task 10: Dashboard Page

**Files:**
- Modify: `frontend/src/pages/Dashboard.tsx`

- [ ] **Step 1: Implement Dashboard**

`frontend/src/pages/Dashboard.tsx`:
```tsx
import { useQuery } from "@tanstack/react-query";
import { api, StatsResponse, InboxListResponse, NoteListResponse } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Link } from "react-router-dom";

export default function DashboardPage() {
  const stats = useQuery<StatsResponse>({ queryKey: ["stats"], queryFn: () => api.stats() });
  const inbox = useQuery<InboxListResponse>({ queryKey: ["inbox"], queryFn: () => api.listInbox({ status: "inbox" }) });
  const recent = useQuery<NoteListResponse>({ queryKey: ["notes", "recent"], queryFn: () => api.listNotes({ per_page: "5" }) });

  return (
    <div className="p-6 space-y-6">
      <h1 className="text-2xl font-bold">概览</h1>

      <div className="grid grid-cols-3 gap-4">
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm text-muted-foreground">笔记总数</CardTitle></CardHeader>
          <CardContent><div className="text-3xl font-bold">{stats.data?.topic_count ?? "—"}</div></CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm text-muted-foreground">待处理</CardTitle></CardHeader>
          <CardContent>
            <div className="text-3xl font-bold">{inbox.data?.total ?? "—"}</div>
            {(inbox.data?.total ?? 0) > 0 && (
              <Link to="/inbox" className="text-sm text-primary hover:underline">去处理</Link>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm text-muted-foreground">分类</CardTitle></CardHeader>
          <CardContent>
            <div className="flex flex-wrap gap-1">
              {stats.data?.categories?.map((c) => (
                <Badge key={c} variant="secondary">{c}</Badge>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader><CardTitle>最近笔记</CardTitle></CardHeader>
        <CardContent>
          {recent.data?.items?.length === 0 ? (
            <p className="text-muted-foreground">暂无笔记</p>
          ) : (
            <div className="space-y-2">
              {recent.data?.items?.map((note) => (
                <Link key={note.path} to={`/notes/${note.path}`} className="block p-2 rounded hover:bg-muted transition-colors">
                  <div className="font-medium">{note.title}</div>
                  <div className="text-sm text-muted-foreground">{note.category} · {note.created?.slice(0, 10)}</div>
                </Link>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
```

- [ ] **Step 2: Verify in browser**

Run: `cd frontend && npm run dev`, open `http://localhost:5173`, verify dashboard renders.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/Dashboard.tsx
git commit -m "feat: implement dashboard page with stats and recent notes"
```

---

## Task 11: Notes Page

**Files:**
- Modify: `frontend/src/pages/Notes.tsx`

- [ ] **Step 1: Implement Notes page**

`frontend/src/pages/Notes.tsx`:
```tsx
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, NoteListResponse, NoteDetail } from "@/lib/api";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

export default function NotesPage() {
  const [category, setCategory] = useState<string>("");
  const [selectedPath, setSelectedPath] = useState<string | null>(null);

  const categories = useQuery({ queryKey: ["categories"], queryFn: () => api.categories() });
  const notes = useQuery<NoteListResponse>({
    queryKey: ["notes", category],
    queryFn: () => api.listNotes(category ? { category } : {}),
  });
  const detail = useQuery<NoteDetail>({
    queryKey: ["note", selectedPath],
    queryFn: () => api.getNote(selectedPath!),
    enabled: !!selectedPath,
  });

  return (
    <div className="flex h-full">
      <div className="w-80 border-r flex flex-col">
        <div className="p-4 space-y-2 border-b">
          <Select value={category} onValueChange={setCategory}>
            <SelectTrigger><SelectValue placeholder="所有分类" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="">所有分类</SelectItem>
              {categories.data?.categories?.map((c) => (
                <SelectItem key={c} value={c}>{c}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="flex-1 overflow-auto">
          {notes.data?.items?.map((note) => (
            <button
              key={note.path}
              onClick={() => setSelectedPath(note.path)}
              className={`w-full text-left p-3 border-b hover:bg-muted transition-colors ${
                selectedPath === note.path ? "bg-muted" : ""
              }`}
            >
              <div className="font-medium text-sm">{note.title}</div>
              <div className="text-xs text-muted-foreground mt-1">
                <Badge variant="outline" className="mr-1">{note.category}</Badge>
                {note.tags?.slice(0, 2).map((t) => <Badge key={t} variant="secondary" className="mr-1">{t}</Badge>)}
              </div>
            </button>
          ))}
          {notes.data?.items?.length === 0 && (
            <p className="p-4 text-sm text-muted-foreground">暂无笔记</p>
          )}
        </div>
      </div>

      <div className="flex-1 overflow-auto">
        {selectedPath && detail.data ? (
          <div className="p-6 max-w-3xl">
            <h1 className="text-2xl font-bold mb-2">{detail.data.title}</h1>
            <div className="flex gap-2 mb-4">
              <Badge>{detail.data.category}</Badge>
              {detail.data.tags?.map((t) => <Badge key={t} variant="secondary">{t}</Badge>)}
            </div>
            <div className="prose prose-sm max-w-none">
              {detail.data.body.split("\n").map((line, i) => (
                <p key={i}>{line}</p>
              ))}
            </div>
          </div>
        ) : (
          <div className="flex items-center justify-center h-full text-muted-foreground">
            选择一篇笔记查看
          </div>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/pages/Notes.tsx
git commit -m "feat: implement notes page with category filter and detail view"
```

---

## Task 12: Inbox Page

**Files:**
- Modify: `frontend/src/pages/Inbox.tsx`

- [ ] **Step 1: Implement Inbox page**

`frontend/src/pages/Inbox.tsx`:
```tsx
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, InboxListResponse, InboxIngestRequest } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export default function InboxPage() {
  const queryClient = useQueryClient();
  const [ingestUrl, setIngestUrl] = useState("");

  const inbox = useQuery<InboxListResponse>({ queryKey: ["inbox"], queryFn: () => api.listInbox() });

  const ingestMutation = useMutation({
    mutationFn: (url: string) => api.ingest({ url_or_text: url }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["inbox"] });
      setIngestUrl("");
    },
  });

  const statusColor: Record<string, string> = {
    inbox: "default",
    processing: "secondary",
    processed: "outline",
    skipped: "destructive",
  };

  return (
    <div className="p-6 space-y-6">
      <h1 className="text-2xl font-bold">收件箱</h1>

      <Card>
        <CardHeader><CardTitle className="text-sm">添加内容</CardTitle></CardHeader>
        <CardContent>
          <div className="flex gap-2">
            <Input
              placeholder="输入 URL 或文本..."
              value={ingestUrl}
              onChange={(e) => setIngestUrl(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && ingestUrl.trim() && ingestMutation.mutate(ingestUrl.trim())}
            />
            <Button onClick={() => ingestUrl.trim() && ingestMutation.mutate(ingestUrl.trim())} disabled={ingestMutation.isPending}>
              添加
            </Button>
          </div>
        </CardContent>
      </Card>

      <div className="space-y-2">
        {inbox.data?.items?.length === 0 ? (
          <p className="text-muted-foreground">收件箱为空</p>
        ) : (
          inbox.data?.items?.map((item) => (
            <Card key={item.path}>
              <CardContent className="p-4 flex items-center justify-between">
                <div>
                  <div className="font-medium">{item.title}</div>
                  <div className="text-sm text-muted-foreground mt-1">
                    {item.source_type} · {item.created?.slice(0, 10)}
                  </div>
                </div>
                <Badge variant={statusColor[item.status] as any}>{item.status}</Badge>
              </CardContent>
            </Card>
          ))
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/pages/Inbox.tsx
git commit -m "feat: implement inbox page with ingest and status display"
```

---

## Task 13: Search Page

**Files:**
- Modify: `frontend/src/pages/Search.tsx`

- [ ] **Step 1: Implement Search page**

`frontend/src/pages/Search.tsx`:
```tsx
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api, SearchResponse } from "@/lib/api";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

export default function SearchPage() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResponse | null>(null);

  const searchMutation = useMutation({
    mutationFn: (q: string) => api.search(q),
    onSuccess: (data) => setResults(data),
  });

  return (
    <div className="p-6 space-y-6">
      <h1 className="text-2xl font-bold">搜索</h1>

      <div className="flex gap-2">
        <Input
          placeholder="语义搜索..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && query.trim() && searchMutation.mutate(query.trim())}
        />
        <Button onClick={() => query.trim() && searchMutation.mutate(query.trim())} disabled={searchMutation.isPending}>
          搜索
        </Button>
      </div>

      {results && (
        <div className="space-y-2">
          <p className="text-sm text-muted-foreground">找到 {results.results.length} 个结果</p>
          {results.results.map((r) => (
            <Card key={r.path}>
              <CardContent className="p-4">
                <div className="flex items-center justify-between mb-2">
                  <span className="font-medium">{r.title}</span>
                  <Badge variant="outline">{(r.score * 100).toFixed(0)}%</Badge>
                </div>
                <p className="text-sm text-muted-foreground">{r.preview}</p>
                <p className="text-xs text-muted-foreground mt-1">{r.path}</p>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/pages/Search.tsx
git commit -m "feat: implement search page with semantic search"
```

---

## Task 14: Writer Page

**Files:**
- Modify: `frontend/src/pages/Writer.tsx`

- [ ] **Step 1: Implement Writer page**

`frontend/src/pages/Writer.tsx`:
```tsx
import { useState, useRef, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, WriterStatus, WriterChatResponse } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

type ChatMessage = { role: "user" | "assistant"; content: string };

export default function WriterPage() {
  const queryClient = useQueryClient();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [idea, setIdea] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  const status = useQuery<WriterStatus>({ queryKey: ["writer-status"], queryFn: () => api.writerStatus(), refetchInterval: 5000 });

  const startMutation = useMutation({
    mutationFn: (idea: string) => api.writerStart(idea),
    onSuccess: (data) => {
      setMessages([{ role: "assistant", content: data.reply }]);
      queryClient.invalidateQueries({ queryKey: ["writer-status"] });
      setIdea("");
    },
  });

  const chatMutation = useMutation({
    mutationFn: (message: string) => api.writerChat(message),
    onMutate: (message) => {
      setMessages((prev) => [...prev, { role: "user", content: message }]);
      setInput("");
    },
    onSuccess: (data) => {
      setMessages((prev) => [...prev, { role: "assistant", content: data.reply }]);
      queryClient.invalidateQueries({ queryKey: ["writer-status"] });
    },
  });

  const publishMutation = useMutation({
    mutationFn: () => api.writerPublish(),
    onSuccess: (data) => {
      setMessages((prev) => [...prev, { role: "assistant", content: data.reply }]);
      queryClient.invalidateQueries({ queryKey: ["writer-status"] });
    },
  });

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages]);

  const stageLabel: Record<string, string> = {
    concept: "核心概念",
    framework: "框架选择",
    content: "内容延展",
    review: "审阅修订",
  };

  return (
    <div className="flex flex-col h-full">
      <div className="p-4 border-b flex items-center justify-between">
        <div className="flex items-center gap-2">
          <h1 className="text-xl font-bold">写作</h1>
          {status.data?.active && (
            <Badge>{stageLabel[status.data.stage ?? ""] ?? status.data.stage}</Badge>
          )}
          {status.data?.title && (
            <span className="text-sm text-muted-foreground">— {status.data.title}</span>
          )}
        </div>
        {status.data?.active && (
          <Button variant="outline" size="sm" onClick={() => publishMutation.mutate()}>发布</Button>
        )}
      </div>

      <div ref={scrollRef} className="flex-1 overflow-auto p-4 space-y-4">
        {messages.length === 0 && !status.data?.active && (
          <div className="text-center text-muted-foreground py-12">
            <p className="text-lg mb-4">开始一个新的写作会话</p>
            <div className="flex gap-2 max-w-md mx-auto">
              <Input
                placeholder="输入你的写作想法..."
                value={idea}
                onChange={(e) => setIdea(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && idea.trim() && startMutation.mutate(idea.trim())}
              />
              <Button onClick={() => idea.trim() && startMutation.mutate(idea.trim())} disabled={startMutation.isPending}>
                开始
              </Button>
            </div>
          </div>
        )}

        {messages.map((msg, i) => (
          <div key={i} className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
            <div className={`max-w-[70%] rounded-lg p-3 ${
              msg.role === "user" ? "bg-primary text-primary-foreground" : "bg-muted"
            }`}>
              <div className="text-sm whitespace-pre-wrap">{msg.content}</div>
            </div>
          </div>
        ))}
      </div>

      {status.data?.active && (
        <div className="p-4 border-t">
          <div className="flex gap-2">
            <Input
              placeholder="输入消息..."
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && input.trim() && chatMutation.mutate(input.trim())}
            />
            <Button onClick={() => input.trim() && chatMutation.mutate(input.trim())} disabled={chatMutation.isPending}>
              发送
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/pages/Writer.tsx
git commit -m "feat: implement writer page with chat interface"
```

---

## Task 15: Podcast Page

**Files:**
- Modify: `frontend/src/pages/Podcast.tsx`

- [ ] **Step 1: Implement Podcast page**

`frontend/src/pages/Podcast.tsx`:
```tsx
import { useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { api, NoteListResponse } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

export default function PodcastPage() {
  const [selectedNote, setSelectedNote] = useState<string>("");
  const [result, setResult] = useState<{ path: string; duration: number } | null>(null);

  const notes = useQuery<NoteListResponse>({
    queryKey: ["notes", "podcast"],
    queryFn: () => api.listNotes({ per_page: "100" }),
  });

  const generateMutation = useMutation({
    mutationFn: (notePath: string) => api.generatePodcast(notePath),
    onSuccess: (data) => setResult(data),
  });

  return (
    <div className="p-6 space-y-6">
      <h1 className="text-2xl font-bold">播客</h1>

      <Card>
        <CardHeader><CardTitle className="text-sm">生成单篇播客</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <Select value={selectedNote} onValueChange={setSelectedNote}>
            <SelectTrigger><SelectValue placeholder="选择一篇笔记" /></SelectTrigger>
            <SelectContent>
              {notes.data?.items?.map((note) => (
                <SelectItem key={note.path} value={note.path}>{note.title}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button
            onClick={() => selectedNote && generateMutation.mutate(selectedNote)}
            disabled={!selectedNote || generateMutation.isPending}
          >
            {generateMutation.isPending ? "生成中..." : "生成播客"}
          </Button>
          {result && (
            <div className="text-sm text-muted-foreground">
              已生成: {result.path} ({result.duration}s)
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/pages/Podcast.tsx
git commit -m "feat: implement podcast page with note selection and generation"
```

---

## Task 16: Full Build Verification

- [ ] **Step 1: Run all backend tests**

Run: `python -m pytest tests/web/ -v`
Expected: All PASS

- [ ] **Step 2: Run all project tests**

Run: `python -m pytest`
Expected: All PASS (no regressions)

- [ ] **Step 3: Build frontend**

Run: `cd frontend && npm run build`
Expected: Build succeeds, output in `lifebook/web/static/`

- [ ] **Step 4: Integration test — start web server**

Run: `lifebook web --port 8081`
Open `http://localhost:8081` in browser.
Verify: SPA loads, sidebar navigation works, API calls succeed.

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "chore: build frontend static assets"
```
