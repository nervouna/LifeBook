"""Shared fixtures and module-level mocks for tests."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

from lifebook.config import (
    Config, KnowledgeConfig, LLMConfig, FeishuConfig,
    ExecutorConfig, DigestConfig, TavilyConfig, FetchConfig, LoggingConfig,
)


# Patch heavy optional dependencies so test collection doesn't fail
# when chromadb / sentence_transformers are not installed.
for mod in (
    "chromadb",
    "chromadb.config",
    "sentence_transformers",
):
    if mod not in sys.modules:
        sys.modules[mod] = MagicMock()


def write_source(sources_dir: Path, filename: str, content: str = "", **meta) -> Path:
    """Write a minimal inbox source file with YAML frontmatter."""
    path = sources_dir / filename
    lines = ["---"]
    for k, v in meta.items():
        lines.append(f"{k}: {v}")
    lines.append("---")
    lines.append(content)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def make_config(tmp_path: Path) -> Config:
    """Create a real Config object rooted at tmp_path."""
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "10-sources").mkdir()
    (kb / "20-topics").mkdir()
    (kb / "30-trajectories").mkdir()
    (kb / "99-publish").mkdir()
    (kb / ".lifebook").mkdir()
    return Config(
        knowledge=KnowledgeConfig(root=kb),
        llm=LLMConfig(),
        feishu=FeishuConfig(),
        executor=ExecutorConfig(),
        digest=DigestConfig(),
        tavily=TavilyConfig(),
        fetch=FetchConfig(),
        logging=LoggingConfig(),
    )
