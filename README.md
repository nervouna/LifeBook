# LifeBook

Personal knowledge base: inbox → LLM extraction → topic notes → vector index. Includes interactive writing agent.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
lifebook init          # create directory structure + config pointer
```

Edit the config file (path shown by `lifebook doctor`) to add API keys.

## Commands

```bash
lifebook process              # process all inbox files
lifebook process --file PATH  # process one file
lifebook serve                # start chat bot
lifebook index --full         # rebuild vector index
lifebook search "query"       # semantic search
lifebook doctor               # check config and environment
```

## Config discovery

Path resolution order:

1. `--config` CLI flag
2. `LIFEBOOK_CONFIG` env var
3. Pointer file in platform-specific app config dir (written by `lifebook init`)
4. Default config path in the knowledge base root
