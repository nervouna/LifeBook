"""Coverage tests for cli.py missing lines."""
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
    cfg.llm.base_url = "https://api.test"
    cfg.llm.model = "test-model"
    cfg.tavily.api_key = "test-tavily-key"
    cfg.tavily.extract_depth = "advanced"
    cfg.feishu.app_id = "test-app-id"
    cfg.feishu.digest_chat_id = "test-chat"
    cfg.executor.batch_limit = 20
    cfg.executor.classify_min_confidence = 0.5
    cfg.executor.max_retries = 3
    cfg.executor.max_workers = 4
    cfg.executor.processing_delay = 0.0
    return cfg


class TestProcessWatchMode:
    def test_watch_runs_once_then_interrupt(self, runner, mock_cfg):
        call_count = 0
        def sleep_side_effect(sec):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise KeyboardInterrupt
        with patch("lifebook.cli.load_config", return_value=mock_cfg):
            with patch("lifebook.executor.Executor") as MockEx:
                MockEx.return_value.process_inbox.return_value = []
                with patch("lifebook.cli.time.sleep", side_effect=sleep_side_effect):
                    result = runner.invoke(main, ["process", "--watch"], catch_exceptions=False)
        assert "Stopped" in result.output or result.exit_code == 0


class TestProcessResults:
    def test_prints_ok_result(self, runner, mock_cfg):
        from lifebook.executor import ProcessResult
        source = mock_cfg.knowledge.sources_path / "test.md"
        source.write_text("---\nstatus: inbox\n---\n", encoding="utf-8")
        topic = mock_cfg.knowledge.topics_path / "test.md"
        with patch("lifebook.cli.load_config", return_value=mock_cfg):
            with patch("lifebook.executor.Executor") as MockEx:
                MockEx.return_value.process_file.return_value = ProcessResult(
                    source, True, topic_path=topic,
                )
                result = runner.invoke(main, ["process", "--file", str(source)], catch_exceptions=False)
        assert result.exit_code == 0

    def test_prints_skipped_result(self, runner, mock_cfg):
        from lifebook.executor import ProcessResult
        source = mock_cfg.knowledge.sources_path / "test.md"
        source.write_text("---\nstatus: inbox\n---\n", encoding="utf-8")
        with patch("lifebook.cli.load_config", return_value=mock_cfg):
            with patch("lifebook.executor.Executor") as MockEx:
                MockEx.return_value.process_file.return_value = ProcessResult(
                    source, False, skipped_reason="low confidence",
                )
                result = runner.invoke(main, ["process", "--file", str(source)], catch_exceptions=False)
        assert result.exit_code == 1

    def test_prints_error_result(self, runner, mock_cfg):
        from lifebook.executor import ProcessResult
        source = mock_cfg.knowledge.sources_path / "test.md"
        source.write_text("---\nstatus: inbox\n---\n", encoding="utf-8")
        with patch("lifebook.cli.load_config", return_value=mock_cfg):
            with patch("lifebook.executor.Executor") as MockEx:
                MockEx.return_value.process_file.return_value = ProcessResult(
                    source, False, error="something broke",
                )
                result = runner.invoke(main, ["process", "--file", str(source)], catch_exceptions=False)
        assert result.exit_code == 1


class TestProcessInboxResults:
    def test_shows_summary_with_skipped_and_failed(self, runner, mock_cfg):
        from lifebook.executor import ProcessResult
        with patch("lifebook.cli.load_config", return_value=mock_cfg):
            with patch("lifebook.executor.Executor") as MockEx:
                MockEx.return_value.process_inbox.return_value = [
                    ProcessResult(mock_cfg.knowledge.sources_path / "a.md", True, topic_path=Path("/x")),
                    ProcessResult(mock_cfg.knowledge.sources_path / "b.md", False, skipped_reason="dup"),
                    ProcessResult(mock_cfg.knowledge.sources_path / "c.md", False, error="fail"),
                ]
                result = runner.invoke(main, ["process"], catch_exceptions=False)
        assert "1 ok" in result.output
        assert "1 skipped" in result.output
        assert "1 failed" in result.output


class TestServeCommand:
    def test_serve_calls_start(self, runner, mock_cfg):
        with patch("lifebook.cli.load_config", return_value=mock_cfg):
            with patch("lifebook.feishu.FeishuBot") as MockBot:
                MockBot.return_value.start = MagicMock(side_effect=KeyboardInterrupt)
                result = runner.invoke(main, ["serve"], catch_exceptions=False)
        MockBot.return_value.start.assert_called_once()


class TestRecoverCommand:
    def test_shows_stale_files(self, runner, mock_cfg):
        with patch("lifebook.cli.load_config", return_value=mock_cfg):
            with patch("lifebook.executor.Executor") as MockEx:
                MockEx.return_value.recover_stale.return_value = [
                    (Path("/tmp/stale.md"), "old"),
                ]
                result = runner.invoke(main, ["recover"], catch_exceptions=False)
        assert "Recovered" in result.output
        assert "stale.md" in result.output

    def test_dry_run(self, runner, mock_cfg):
        with patch("lifebook.cli.load_config", return_value=mock_cfg):
            with patch("lifebook.executor.Executor") as MockEx:
                MockEx.return_value.recover_stale.return_value = [
                    (Path("/tmp/stale.md"), "old"),
                ]
                result = runner.invoke(main, ["recover", "--dry-run"], catch_exceptions=False)
        assert "Would recover" in result.output


@pytest.fixture
def mock_chromadb_modules():
    mock_chromadb = MagicMock()
    mock_chromadb.config = MagicMock()
    mock_st = MagicMock()
    saved = {}
    mods = {
        "chromadb": mock_chromadb,
        "chromadb.config": mock_chromadb.config,
        "sentence_transformers": mock_st,
    }
    for name, mod in mods.items():
        if name in sys.modules:
            saved[name] = sys.modules[name]
        sys.modules[name] = mod
    yield
    for name in mods:
        if name in saved:
            sys.modules[name] = saved[name]
        else:
            sys.modules.pop(name, None)


class TestIndexCommand:
    def test_index_with_interval(self, runner, mock_cfg, mock_chromadb_modules):
        with patch("lifebook.cli.load_config", return_value=mock_cfg):
            from lifebook.indexer import Indexer
            with patch.object(Indexer, "__init__", return_value=None):
                with patch.object(Indexer, "start"):
                    with patch.object(Indexer, "stop"):
                        with patch("lifebook.cli.time.sleep", side_effect=KeyboardInterrupt):
                            result = runner.invoke(main, ["index", "--interval", "60"], catch_exceptions=False)
        assert "60s" in result.output or result.exit_code == 0

    def test_index_with_errors(self, runner, mock_cfg, mock_chromadb_modules):
        stats = {"upserted": 0, "deleted": 0, "unchanged": 0, "errors": 6}
        with patch("lifebook.cli.load_config", return_value=mock_cfg):
            from lifebook.indexer import Indexer
            with patch.object(Indexer, "__init__", return_value=None):
                with patch.object(Indexer, "incremental_update", return_value=stats):
                    result = runner.invoke(main, ["index"], catch_exceptions=False)
        assert "Errors: 6" in result.output


class TestSearchCommand:
    def test_search_no_results(self, runner, mock_cfg, mock_chromadb_modules):
        with patch("lifebook.cli.load_config", return_value=mock_cfg):
            from lifebook.vector import VectorIndex
            with patch.object(VectorIndex, "__init__", return_value=None):
                with patch.object(VectorIndex, "search", return_value=[]):
                    result = runner.invoke(main, ["search", "test query"], catch_exceptions=False)
        assert "No results" in result.output

    def test_search_with_results(self, runner, mock_cfg, mock_chromadb_modules):
        from types import SimpleNamespace
        results = [
            SimpleNamespace(doc_id="doc1", distance=0.1, metadata={"title": "Test"}, text="A" * 100),
        ]
        with patch("lifebook.cli.load_config", return_value=mock_cfg):
            from lifebook.vector import VectorIndex
            with patch.object(VectorIndex, "__init__", return_value=None):
                with patch.object(VectorIndex, "search", return_value=results):
                    result = runner.invoke(main, ["search", "test"], catch_exceptions=False)
        assert "Found 1 results" in result.output
        assert "Test" in result.output


class TestPublishCommand:
    def test_publish_cmd(self, runner, mock_cfg):
        with patch("lifebook.cli.load_config", return_value=mock_cfg):
            with patch("lifebook.writer.Writer") as MockW:
                with patch("lifebook.llm.LLMClient"):
                    MockW.return_value.publish.return_value = "已发布"
                    result = runner.invoke(main, ["publish"], catch_exceptions=False)
        assert "已发布" in result.output


class TestWriterStatusCommand:
    def test_active(self, runner, mock_cfg):
        with patch("lifebook.cli.load_config", return_value=mock_cfg):
            with patch("lifebook.writer.Writer") as MockW:
                with patch("lifebook.llm.LLMClient"):
                    MockW.return_value.active = True
                    MockW.return_value.stage = "drafting"
                    result = runner.invoke(main, ["writer-status"], catch_exceptions=False)
        assert "进行中" in result.output

    def test_inactive(self, runner, mock_cfg):
        with patch("lifebook.cli.load_config", return_value=mock_cfg):
            with patch("lifebook.writer.Writer") as MockW:
                with patch("lifebook.llm.LLMClient"):
                    MockW.return_value.active = False
                    result = runner.invoke(main, ["writer-status"], catch_exceptions=False)
        assert "未启动" in result.output


class TestRestoreCommand:
    def test_restore_cmd(self, runner, mock_cfg):
        with patch("lifebook.cli.load_config", return_value=mock_cfg):
            with patch("lifebook.writer.Writer") as MockW:
                with patch("lifebook.llm.LLMClient"):
                    MockW.return_value.restore_draft.return_value = "已恢复"
                    result = runner.invoke(main, ["restore"], catch_exceptions=False)
        assert "已恢复" in result.output


class TestMainEntry:
    def test_main_if_name(self):
        import lifebook.cli as cli_mod
        assert hasattr(cli_mod, "main")

    def test_main_block(self):
        """Line 287: __name__ == '__main__' block."""
        import runpy
        with patch("lifebook.cli.load_config") as mock_load:
            mock_load.side_effect = SystemExit(0)
            try:
                runpy.run_module("lifebook.cli", run_name="__main__")
            except SystemExit:
                pass


class TestPodcastCommand:
    def test_podcast_happy_path(self, runner, mock_cfg, tmp_path):
        note = tmp_path / "test_note.md"
        note.write_text("---\ntitle: Test\n---\nContent\n", encoding="utf-8")

        with patch("lifebook.cli.load_config", return_value=mock_cfg):
            with patch("lifebook.podcast.PodcastGenerator") as MockGen:
                gen_inst = MockGen.return_value
                gen_inst.generate.return_value = (b"fake_mp3", 30)
                result = runner.invoke(main, ["podcast", str(note)], catch_exceptions=False)
        assert result.exit_code == 0
        assert "Generating podcast" in result.output
        assert "Saved" in result.output

    def test_podcast_custom_output(self, runner, mock_cfg, tmp_path):
        note = tmp_path / "test_note.md"
        note.write_text("---\ntitle: Test\n---\nContent\n", encoding="utf-8")
        out = tmp_path / "custom.mp3"

        with patch("lifebook.cli.load_config", return_value=mock_cfg):
            with patch("lifebook.podcast.PodcastGenerator") as MockGen:
                gen_inst = MockGen.return_value
                gen_inst.generate.return_value = (b"fake_mp3", 30)
                result = runner.invoke(
                    main, ["podcast", str(note), "-o", str(out)],
                    catch_exceptions=False,
                )
        assert result.exit_code == 0
        assert out.exists()


class TestPodcastMultiCommand:
    def test_podcast_multi_happy_path(self, runner, mock_cfg, tmp_path):
        mock_cfg.knowledge.topics_path = tmp_path / "topics"
        mock_cfg.knowledge.topics_path.mkdir()

        with patch("lifebook.cli.load_config", return_value=mock_cfg):
            with patch("lifebook.podcast.select_notes") as mock_select:
                n1 = tmp_path / "topics" / "a.md"
                n1.write_text("---\ntitle: A\n---\nC\n", encoding="utf-8")
                mock_select.return_value = ([n1], 1)
                with patch("lifebook.podcast.PodcastGenerator") as MockGen:
                    gen_inst = MockGen.return_value
                    gen_inst.generate_multi.return_value = (b"fake_mp3", 30)
                    result = runner.invoke(
                        main, ["podcast-multi", "--since", "2026-01-01"],
                        catch_exceptions=False,
                    )
        assert result.exit_code == 0
        assert "Found 1 notes" in result.output
        assert "Saved" in result.output

    def test_podcast_multi_no_notes(self, runner, mock_cfg, tmp_path):
        mock_cfg.knowledge.topics_path = tmp_path / "topics"
        mock_cfg.knowledge.topics_path.mkdir()

        with patch("lifebook.cli.load_config", return_value=mock_cfg):
            with patch("lifebook.podcast.select_notes") as mock_select:
                mock_select.return_value = ([], 0)
                result = runner.invoke(
                    main, ["podcast-multi", "--since", "2026-01-01"],
                    catch_exceptions=False,
                )
        assert result.exit_code == 1
        assert "No notes found" in result.output
