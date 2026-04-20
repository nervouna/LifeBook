# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install (from project root, using venv)
.venv/bin/python -m pip install -e .

# Run tests
python -m pytest

# Run a single test
python -m pytest -k "test_name"

# CLI
lifebook process              # process all inbox files
lifebook process --file PATH  # process single file
lifebook serve                # start Feishu bot (blocks)
lifebook index --full         # rebuild vector index
lifebook search "query"       # semantic search
lifebook doctor               # check config and environment
```

## Architecture

Knowledge base system: inbox sources → LLM extraction → topic notes → vector index.

- **executor.py**: core pipeline. Claims file (fcntl lock), fetches URL, calls LLM, validates, writes topic note.
- **llm.py**: Anthropic Messages API wrapper. `structured_call` (forced tool_use), `text_call`, `agentic_call` (multi-turn tool loop). Includes DeepSeek XML fallback parser.
- **feishu.py**: WebSocket bot. Slash commands: `/write`, `/publish`, `/process`, `/update-index`, `/search`, `/status`.
- **writer.py**: interactive writing agent with draft stages (concept → framework → content → review → publish).
- **prompts.py**: LLM system prompts and tool schemas with strict output formatting rules. Modifying schemas here changes LLM behavior — test after changes.
- **store.py**: filesystem abstraction with fcntl-based file locking (macOS/Linux only).

Data lives at `~/Documents/Knowledge/`, config at `~/Documents/Knowledge/.lifebook/config.yaml`.

## Testing

- Tests use `unittest.mock.MagicMock` extensively.
- Patch targets are import-path specific: `patch("lifebook.llm.anthropic.Anthropic")`, `patch("lifebook.executor.LLMClient")`.
- Executor tests mock LLM and Fetcher at the class level; use `executor.llm.structured_call.return_value` for return values.
- No CI configured — run `python -m pytest` manually before committing.

## Code Style

- Type hints everywhere. `from __future__ import annotations`.
- No comments unless documenting a hack or non-obvious constraint.
- All identifiers and comments in English. User-facing strings may be Chinese.
- Commit format: `type: lowercase message` (no period). Types: feat/fix/refactor/test/chore/doc/style/perf.
- Tags must be Obsidian-compatible (alphanumeric + hyphens, no spaces).
- File locking via `fcntl.flock` — macOS/Linux only, not portable to Windows.
