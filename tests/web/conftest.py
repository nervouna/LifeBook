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
