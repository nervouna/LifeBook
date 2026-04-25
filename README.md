# LifeBook

Personal knowledge base: inbox → LLM extraction → topic notes → vector index → podcast. Includes a web workbench for browsing notes, semantic search, and an interactive writing agent.

## Setup

Requires Python ≥ 3.10.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
lifebook init
```

Edit the config file (path shown by `lifebook doctor`) to add API keys.

## Commands

```bash
lifebook process                  # process inbox files
lifebook process --watch          # watch inbox for changes
lifebook ingest URL_OR_TEXT       # add URL or text to inbox
lifebook recover                  # rollback stuck files
lifebook index                    # update vector index
lifebook index --full             # rebuild vector index
lifebook search "query"           # semantic search
lifebook writer-status            # check writing session
lifebook publish                  # finalize current draft
lifebook restore                  # restore draft from backup
lifebook serve                    # start Feishu bot
lifebook doctor                   # check config and environment
lifebook digest                   # generate daily digest
lifebook podcast NOTE_PATH        # generate podcast from single note
lifebook podcast NOTE_PATH --send # generate and send to Feishu
lifebook podcast-multi --since 2026-04-22 --limit 10 --send  # combined episode
lifebook web                      # start web UI (default: http://127.0.0.1:8080)
lifebook web --port 9000          # custom port
lifebook web --reload             # auto-reload for development
```

## Config

See `config.example.yaml`. Required keys: `llm` (API key + model), `knowledge.root`. Optional: `feishu`, `feishu_podcast`, `tavily`, `vision`, `tts`.

Resolution order: `--config` flag → `LIFEBOOK_CONFIG` env → pointer file → default in knowledge root.

## Web UI

`lifebook web` starts a single-process server that serves both the REST API and a React SPA.

```bash
pip install -e .                  # web dependencies included
lifebook web                      # http://127.0.0.1:8080
```

For frontend development with hot reload:

```bash
cd frontend && npm install && npm run dev   # http://localhost:5173 (proxies API to :8080)
```

Frontend build output goes to `lifebook/web/static/` and is served by FastAPI automatically.
