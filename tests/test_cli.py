"""Unit tests for CLI commands."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from lifebook.cli import main


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def mock_cfg(tmp_path):
    """Create a minimal mock config for CLI testing."""
    sources = tmp_path / "10-sources"
    sources.mkdir()
    topics = tmp_path / "20-topics"
    topics.mkdir()
    state = tmp_path / ".lifebook"
    state.mkdir()

    cfg = MagicMock()
    cfg.knowledge.root = tmp_path
    cfg.knowledge.sources_path = sources
    cfg.knowledge.topics_path = topics
    cfg.knowledge.state_path = state
    cfg.knowledge.trajectories_path = tmp_path / "30-trajectories"
    cfg.logging.level = "INFO"
    cfg.llm.api_key = "test-key"
    cfg.llm.base_url = "https://api.test.com"
    cfg.llm.model = "test-model"
    cfg.tavily.api_key = "test-tavily-key"
    cfg.tavily.extract_depth = "advanced"
    cfg.feishu.app_id = "test-app-id"
    cfg.feishu.digest_chat_id = "test-chat"
    cfg.executor.batch_limit = 20
    cfg.executor.classify_min_confidence = 0.5
    return cfg


def _invoke(runner, args, mock_cfg):
    """Invoke CLI with a patched load_config."""
    with patch("lifebook.cli.load_config", return_value=mock_cfg):
        return runner.invoke(main, args, catch_exceptions=False)


class TestDoctorCommand:
    def test_shows_checks(self, runner, mock_cfg):
        result = _invoke(runner, ["doctor"], mock_cfg)
        assert result.exit_code == 0
        assert "LLM API key" in result.output
        assert "Tavily API key" in result.output
        assert "Feishu app_id" in result.output


class TestIngestCommand:
    def test_ingests_url(self, runner, mock_cfg):
        with patch("lifebook.cli.load_config", return_value=mock_cfg):
            with patch("lifebook.ingest.ingest_url") as mock_ingest:
                mock_ingest.return_value = mock_cfg.knowledge.sources_path / "link-test.md"
                result = runner.invoke(main, ["ingest", "https://example.com"], catch_exceptions=False)

        assert result.exit_code == 0
        assert "Ingested" in result.output
        mock_ingest.assert_called_once()

    def test_ingests_text(self, runner, mock_cfg):
        with patch("lifebook.cli.load_config", return_value=mock_cfg):
            with patch("lifebook.ingest.ingest_text") as mock_ingest:
                mock_ingest.return_value = mock_cfg.knowledge.sources_path / "note-test.md"
                result = runner.invoke(main, ["ingest", "some text note"], catch_exceptions=False)

        assert result.exit_code == 0
        assert "Ingested" in result.output
        mock_ingest.assert_called_once()


class TestProcessCommand:
    def test_process_empty_inbox(self, runner, mock_cfg):
        with patch("lifebook.cli.load_config", return_value=mock_cfg):
            with patch("lifebook.executor.Executor") as MockEx:
                mock_ex = MockEx.return_value
                mock_ex.process_inbox.return_value = []
                result = runner.invoke(main, ["process"], catch_exceptions=False)

        assert result.exit_code == 0
        assert "0 total" in result.output

    def test_process_single_file(self, runner, mock_cfg):
        from lifebook.executor import ProcessResult

        # Create an actual file so click's exists=True check passes
        source_path = mock_cfg.knowledge.sources_path / "test.md"
        source_path.write_text("---\nstatus: inbox\n---\ncontent\n", encoding="utf-8")
        topic_path = mock_cfg.knowledge.topics_path / "AI技术" / "test.md"

        with patch("lifebook.cli.load_config", return_value=mock_cfg):
            with patch("lifebook.executor.Executor") as MockEx:
                mock_ex = MockEx.return_value
                mock_ex.process_file.return_value = ProcessResult(
                    source_path, True, topic_path=topic_path,
                )
                result = runner.invoke(
                    main, ["process", "--file", str(source_path)],
                    catch_exceptions=False,
                )

        assert result.exit_code == 0


@pytest.fixture
def mock_chromadb_modules():
    """Mock chromadb and sentence_transformers modules for indexer import."""
    mock_chromadb = MagicMock()
    mock_chromadb.config = MagicMock()
    mock_st = MagicMock()

    saved = {}
    mods_to_mock = {
        "chromadb": mock_chromadb,
        "chromadb.config": mock_chromadb.config,
        "sentence_transformers": mock_st,
    }
    for name, mod in mods_to_mock.items():
        if name in sys.modules:
            saved[name] = sys.modules[name]
        sys.modules[name] = mod

    yield

    for name in mods_to_mock:
        if name in saved:
            sys.modules[name] = saved[name]
        else:
            sys.modules.pop(name, None)


class TestIndexCommand:
    def test_incremental_update(self, runner, mock_cfg, mock_chromadb_modules):
        stats = {"upserted": 3, "deleted": 1, "unchanged": 5, "errors": 0}

        with patch("lifebook.cli.load_config", return_value=mock_cfg):
            # Import after mocking
            from lifebook.indexer import Indexer
            with patch.object(Indexer, "__init__", return_value=None):
                with patch.object(Indexer, "incremental_update", return_value=stats):
                    result = runner.invoke(main, ["index"], catch_exceptions=False)

        assert result.exit_code == 0
        assert "Upserted: 3" in result.output

    def test_full_rebuild(self, runner, mock_cfg, mock_chromadb_modules):
        stats = {"upserted": 10, "deleted": 0, "unchanged": 0, "errors": 0}

        with patch("lifebook.cli.load_config", return_value=mock_cfg):
            from lifebook.indexer import Indexer
            with patch.object(Indexer, "__init__", return_value=None):
                with patch.object(Indexer, "full_rebuild", return_value=stats):
                    result = runner.invoke(main, ["index", "--full"], catch_exceptions=False)

        assert result.exit_code == 0
        assert "Upserted: 10" in result.output


class TestRecoverCommand:
    def test_no_stale(self, runner, mock_cfg):
        with patch("lifebook.cli.load_config", return_value=mock_cfg):
            with patch("lifebook.executor.Executor") as MockEx:
                MockEx.return_value.recover_stale.return_value = []
                result = runner.invoke(main, ["recover"], catch_exceptions=False)

        assert result.exit_code == 0
        assert "No files stuck" in result.output
