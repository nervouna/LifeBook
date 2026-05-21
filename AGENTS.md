# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Commands

```bash
# Install toolchain + runtime deps (from project root)
mise install
uv sync
# For semantic search / vector index work: uv sync --extra index

# Install dev/test deps when you need pytest
uv sync --group dev

# Run tests
uv run pytest

# Run a single test
uv run pytest -k "test_name"

# CLI
uv run lifebook init              # create directory structure + config
uv run lifebook process           # process all inbox files
uv run lifebook process --file PATH # process single file
uv run lifebook process --watch   # watch inbox for changes
uv run lifebook ingest URL_OR_TEXT # add URL or text to inbox
uv run lifebook recover           # rollback files stuck in processing
uv run lifebook retry             # retry files that failed fetching
uv run lifebook index             # incremental vector index update
uv run lifebook index --full      # rebuild vector index
uv run lifebook search "query"    # semantic search
uv run lifebook writer-status     # check current writing session
uv run lifebook publish           # finalize current draft
uv run lifebook restore           # restore draft from backup
uv run lifebook restore-published # restore most recently published draft from archive
uv run lifebook serve             # start Feishu bot (blocks)
uv run lifebook doctor            # check config and environment
uv run lifebook digest            # generate daily digest
uv run lifebook podcast NOTE_PATH # generate podcast from single note
uv run lifebook podcast NOTE_PATH --send # generate and send to Feishu
uv run lifebook podcast-multi --since 2026-04-22 --limit 10 --send  # combined episode from recent notes
uv run lifebook web                # start FastAPI web server (default 127.0.0.1:8080)
uv run lifebook web --port 3000 --reload  # custom port with auto-reload

# Frontend (from frontend/ directory)
mise exec -- corepack pnpm install  # install frontend dependencies
mise exec -- corepack pnpm run dev   # Vite dev server with hot reload (port 5173)
mise exec -- corepack pnpm run build # build SPA → lifebook/web/static/
mise exec -- corepack pnpm run lint  # run ESLint
```

## Architecture

Knowledge base system: inbox sources → LLM extraction → topic notes → vector index.

Core pipeline:
- **cli.py**: Click CLI entry point. All commands registered here.
- **executor.py**: core pipeline. Claims file (fcntl lock), fetches URL, calls LLM, validates, writes topic note.
- **ingest.py**: add URLs or raw text snippets to the inbox.
- **fetcher.py**: web content fetching with readability extraction and domain skip list.
- **llm.py**: Anthropic Messages API wrapper. `structured_call` (forced tool_use), `text_call`, `agentic_call` (multi-turn tool loop). Includes DeepSeek XML fallback parser.
- **prompts/**: LLM system prompts package. `extract.py` (inbox extraction prompts/schemas), `writer.py` (writing agent prompts/schemas). Modifying schemas here changes LLM behavior — test after changes.

Index & search:
- **indexer.py**: incremental and full vector index rebuild orchestration.
- **vector.py**: ChromaDB + SentenceTransformers semantic search layer.
- **notes.py**: topic note file parsing and frontmatter handling.

Writing agent:
- **writer.py**: interactive writing agent with draft stages (concept → framework → content → review → publish). File structure: `draft.json` (metadata), `draft.md` (content), `draft.history.json` (discussion).

Podcast:
- **podcast.py**: topic notes → monologue script (Mia/大毛) → TTS → audio. `select_notes` picks by date/limit. `generate` (single note) and `generate_multi` (combined episode).
- **tts.py**: MiMo TTS client via OpenAI-compatible chat completions API. Single `synthesize(text) -> bytes` call.

Web UI:
- **web/app.py**: FastAPI application factory. Serves API routes + static frontend SPA.
- **web/api/**: route modules — `inbox.py`, `notes.py`, `podcast.py`, `search.py`, `system.py`, `writer.py`.
- **web/services/**: business logic layer — `inbox_service.py`, `note_service.py`, `search_service.py`, `writer_service.py`.
- **web/schemas.py**: Pydantic request/response models.
- **web/static/**: pre-built React SPA (Vite output). Source in `frontend/`.
- **frontend/**: Vite + React + TypeScript SPA source. `npm run build` outputs to `lifebook/web/static/`.

Bot & transport:
- **feishu.py**: thin coordinator — delegates to `feishu_commands.py` (CommandRouter) and `feishu_handler.py` (MessageHandler).
- **feishu_commands.py**: slash command dispatch logic.
- **feishu_handler.py**: message type handlers (image/URL/text).
- **feishu_transport.py**: Feishu WebSocket transport layer. `send_card` for interactive cards, `update_card` for patching cards. Card action callbacks via `register_p2_card_action_trigger`.

Infrastructure:
- **config.py**: YAML config loading and validation.
- **store.py**: filesystem abstraction with fcntl-based file locking (macOS/Linux only).
- **image_processor.py**: image compression and resizing for LLM vision input.
- **audio.py**: audio processing utilities (concat, opus conversion, duration).

Data lives at `~/Documents/Knowledge/`, config at `~/Documents/Knowledge/.lifebook/config.yaml`.

## Environment

- `ANTHROPIC_API_KEY` — required for LLM calls. Set in shell or `.env`.
- Create `.env` at project root (already in `.gitignore`).
- Config file: `~/Documents/Knowledge/.lifebook/config.yaml` (created by `uv run lifebook init`).

## Testing

- Tests use `unittest.mock.MagicMock` extensively.
- Patch targets are import-path specific: `patch("lifebook.llm.anthropic.Anthropic")`, `patch("lifebook.executor.LLMClient")`.
- Executor tests mock LLM and Fetcher at the class level; use `executor.llm.structured_call.return_value` for return values.
- Web API tests (`tests/web/`) use FastAPI `TestClient` with dependency-overridden services.
- Web test `conftest.py` overrides service dependencies with mocks; see `tests/web/conftest.py` for the pattern.
- ChromaDB mock chain in `tests/conftest.py` must include `chromadb`, `chromadb.config`, `chromadb.utils`, and `chromadb.utils.embedding_functions`.
- No CI configured — run `uv run pytest` manually before committing.

## Dev Flow

1. TDD: write failing test first, implement to pass, then refactor
2. Run `/simplify` before each commit
3. Commit in minimal logical batches
4. After changes to core modules (llm, vector, executor, podcast), run end-to-end: `uv run lifebook ingest` → `uv run lifebook process` → `uv run lifebook index` → `uv run lifebook search` → `uv run lifebook podcast`

## Code Style

- Type hints everywhere. `from __future__ import annotations`.
- No comments unless documenting a hack or non-obvious constraint.
- All identifiers and comments in English. User-facing strings may be Chinese.
- Commit format: `type: lowercase message` (no period). Types: feat/fix/refactor/test/chore/doc/style/perf.
- Tags must be Obsidian-compatible (alphanumeric + hyphens, no spaces).
- File locking via `fcntl.flock` — macOS/Linux only, not portable to Windows.

## Gotchas

- `lifebook process --file` requires an absolute path, not relative.
- ChromaDB 1.5.x requires `SentenceTransformerEmbeddingFunction` from `chromadb.utils.embedding_functions` — do not use custom embedding function classes.
- `ffprobe` returns bytes; decode with `.utf-8` and handle `N/A` for missing duration.
- `config.py` merge conflicts often break indentation — verify after every merge.
