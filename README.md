# LifeBook

Personal knowledge base: inbox → LLM extraction → topic notes → vector index.

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
```

## Config

See `config.example.yaml`. Required keys: `llm` (API key + model), `knowledge.root`. Optional: `feishu`, `tavily`, `vision`.

Resolution order: `--config` flag → `LIFEBOOK_CONFIG` env → pointer file → default in knowledge root.
