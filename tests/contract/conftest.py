"""契约测试层 fixtures。LLM 全 fake，其余（文件系统、frontmatter、Executor）走真实路径。

注：顶层 tests/conftest.py 已经全局 mock 了 chromadb / sentence_transformers，此处无需再 mock。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from lifebook.config import (
    Config, KnowledgeConfig, LLMConfig, FeishuConfig,
    ExecutorConfig, DigestConfig, TavilyConfig, FetchConfig, LoggingConfig,
)
from lifebook.executor import Executor
from lifebook.writer import Writer

from ._helpers import FakeFetcher, FakeLLMClient


def _make_config(tmp_path: Path) -> Config:
    """Real Config rooted at tmp_path."""
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


# --------- Fixtures ---------

@pytest.fixture
def cfg(tmp_path: Path):
    """Real Config rooted at tmp_path. Categories include those used in tests."""
    config = _make_config(tmp_path)
    # 缩短 fetch 重试上限以便 retry 测试更快
    config.executor.max_retries = 2
    config.executor.processing_delay = 0
    config.executor.max_workers = 1  # serialize for deterministic assertions
    return config


@pytest.fixture
def fake_llm():
    return FakeLLMClient()


@pytest.fixture
def fake_fetcher():
    return FakeFetcher()


@pytest.fixture
def make_executor(cfg, fake_llm, fake_fetcher):
    """Build an Executor wired with fakes."""
    def _build():
        return Executor(cfg=cfg, llm=fake_llm, fetcher=fake_fetcher)
    return _build


@pytest.fixture
def make_writer(cfg, fake_llm):
    """Build a Writer wired with the fake LLM."""
    def _build():
        return Writer(cfg=cfg, llm=fake_llm)
    return _build
