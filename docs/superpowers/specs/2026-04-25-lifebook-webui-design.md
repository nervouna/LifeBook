# LifeBook WebUI Design

## Overview

Add a web-based workbench to LifeBook for browsing notes, managing inbox, semantic search, and an interactive writing agent. Single-process deployment: FastAPI serves both REST API and React SPA.

## Goals

- Replace CLI for daily operations with a visual workbench
- Deep integration of writing agent as chat interface
- Real-time feedback for long-running operations (process, podcast)
- Personal tool, single-user, local deployment

## Non-Goals

- Multi-user auth (single-user local tool)
- Mobile-responsive design (desktop-first)
- Real-time collaboration
- Note editing (read + metadata edit only in V1; full editing in later versions)

## Architecture

```
React SPA (Tailwind + shadcn/ui)
    REST + SSE
FastAPI (api layer)
    ↕
Web Service Layer (pagination, filtering, aggregation)
    ↕
Core Classes (Executor, VectorIndex, Writer, PodcastGenerator, NoteStore)
    ↕
Filesystem + ChromaDB
```

### Directory Structure

```
lifebook/
  web/
    __init__.py
    app.py          # FastAPI app factory, mount static
    api/
      __init__.py
      notes.py      # Note CRUD + listing
      inbox.py      # Inbox listing + processing
      search.py     # Semantic search
      writer.py     # Writing agent chat
      podcast.py    # Podcast generation
      system.py     # Doctor, index, stats
    services/
      __init__.py
      note_service.py
      inbox_service.py
      search_service.py
      writer_service.py
    schemas.py      # Pydantic request/response models
    static/         # Vite build output
  frontend/         # React source (separate from Python package)
    src/
      components/
      pages/
      hooks/
      lib/
    package.json
    vite.config.ts
    tailwind.config.ts
```

## API Design

### Notes

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/notes` | Paginated list, filter by category/tag/status |
| GET | `/api/notes/{path}` | Single note detail (frontmatter + body) |
| PUT | `/api/notes/{path}` | Edit frontmatter or body |
| DELETE | `/api/notes/{path}` | Delete note |

### Inbox

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/inbox` | List inbox items, filter by status |
| POST | `/api/inbox` | Ingest URL or text |
| POST | `/api/inbox/{path}/process` | Process single item (SSE) |
| POST | `/api/inbox/process-all` | Batch process (SSE) |

### Search

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/search` | Semantic search, returns ranked results |

### Writer

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/writer/status` | Current stage + draft metadata |
| POST | `/api/writer/start` | New writing session |
| POST | `/api/writer/chat` | Chat interaction (SSE streaming) |
| POST | `/api/writer/publish` | Publish draft |
| POST | `/api/writer/restore` | Restore from backup |

### Podcast

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/podcast/generate` | Single note podcast (SSE) |
| POST | `/api/podcast/generate-multi` | Combined episode (SSE) |

### System

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/system/doctor` | Health check |
| POST | `/api/system/index` | Rebuild vector index |
| GET | `/api/system/stats` | Note count, inbox count, index status |
| GET | `/api/system/categories` | Category list |
| GET | `/api/system/tags` | Tag list |

### SSE Protocol

Unified event format for all streaming endpoints:

```
event: progress
data: {"step": "fetching", "message": "正在获取网页内容...", "progress": 0.3}

event: done
data: {"result": {...}}

event: error
data: {"message": "处理失败：网络超时"}
```

### Error Response

```json
{"error": "string", "detail": "optional string"}
```

## Frontend Design

### Layout

Left sidebar navigation + main content area. Writing mode adds a right-side chat panel.

```
┌─────────────────────────────────────────────┐
│  [Logo] LifeBook          [Search] [Stats]  │
├────────┬────────────────────────────────────┤
│        │                                    │
│ 📊 概览 │     Main content area              │
│ 📥 收件箱│     (switches per nav item)        │
│ 📝 笔记 │                                    │
│ ✍️ 写作 │                         ┌────────┐ │
│ 🔍 搜索 │                         │ Chat   │ │
│ 🎙️ 播客 │                         │ Panel  │ │
│        │                         └────────┘ │
└────────┴────────────────────────────────────┘
```

### Pages

| Page | Function |
|------|----------|
| **概览 (Dashboard)** | Inbox count, recent notes, writing progress, system status |
| **收件箱 (Inbox)** | List + batch process buttons, expand for detail, SSE progress |
| **笔记 (Notes)** | Category tree + note list + detail/edit, filter by category/tag/keyword |
| **写作 (Writer)** | Chat interface + draft preview panel, shows current stage |
| **搜索 (Search)** | Search box + ranked results, click to view note detail |
| **播客 (Podcast)** | Select notes → generate → audio player, single + multi |

### Components

shadcn/ui: Card, Table, Dialog, Command, Sheet, Tabs, Badge, ScrollArea, Button, Input, Select, toast.

### State Management

TanStack Query for server state (cache + auto-refetch). No global client state store needed.

## Data Flow

### Note Browsing

```
Frontend → GET /api/notes?category=X&page=1
         → NoteService.list(category, page, per_page)
         → NoteStore.list_sources() / list_topics()
         → Filter + paginate
         → Return {items: [...], total: N, page: P}
```

### Inbox Processing (SSE)

```
Frontend → POST /api/inbox/{path}/process
         → InboxService.process_single(path)
         → yield SSE progress events
         → Executor.process_file(path)  [existing]
         → yield SSE done event
```

### Writing Chat (SSE)

```
Frontend → POST /api/writer/chat {message: "..."}
         → WriterService.chat(message)
         → Writer.chat(message)  [existing]
         → yield SSE events for agent tool_use + text
         → Frontend renders Markdown incrementally
```

## Build & Deployment

- Frontend: Vite + React + Tailwind, `corepack pnpm run build` outputs to `lifebook/web/static/`
- Backend: FastAPI serves `/api/*` routes + mounts `static/` for SPA
- Start: `lifebook web` CLI command (new), runs uvicorn on configurable port (default 8080)
- Config: add `web` section to config.yaml (port, host)

## Testing

- Backend: pytest with mocked services (same pattern as existing tests)
- Frontend: Vitest for component tests
- Integration: manual testing for V1

## Implementation Order

1. Backend API + service layer (FastAPI, schemas, services)
2. CLI `lifebook web` command
3. Frontend scaffolding (Vite + React + Tailwind + shadcn/ui)
4. Dashboard page
5. Notes page (browse + search)
6. Inbox page
7. Writer page (chat + draft preview)
8. Podcast page
