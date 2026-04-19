"""Tests for CLI write/publish commands."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from lifebook.cli import main
from lifebook.config import (
    Config, KnowledgeConfig, LLMConfig, FeishuConfig,
    ExecutorConfig, DigestConfig, TavilyConfig, FetchConfig, LoggingConfig,
)
from lifebook.notes import new_post, write_note, read_note
from lifebook.writer import STAGE_CONTENT, STAGE_CONCEPT


def make_cfg(tmp_path: Path) -> Config:
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "20-topics").mkdir()
    (kb / "99-publish").mkdir()
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


CONCEPT_RESULT = {
    "topic": "测试主题",
    "thesis": "测试主张",
    "audience": "测试读者",
    "concept_text": "这是核心概念文本。",
}

FRAMEWORK_RESULT = {
    "frameworks": [
        {
            "name": "方案A",
            "outline": [
                {"heading": "引言", "point": "引入话题"},
                {"heading": "论证", "point": "展开论证"},
            ],
        },
    ]
}

CONTENT_TEXT = "## 引言\n\n引言内容。\n\n## 论证\n\n论证内容。\n"


class TestCLIWriterCommands:
    def test_publish_command_no_draft(self, tmp_path):
        """/publish with no draft should report no active writing."""
        cfg = make_cfg(tmp_path)
        runner = CliRunner()
        with patch("lifebook.cli.load_config", return_value=cfg):
            result = runner.invoke(main, ["publish"])
            assert result.exit_code == 0
            assert "没有" in result.output

    def test_publish_command_with_draft(self, tmp_path):
        """/publish on existing draft at content stage should succeed."""
        cfg = make_cfg(tmp_path)
        # Create a draft manually
        draft_path = cfg.knowledge.publish_path / "draft.md"
        post = new_post(
            "## 核心概念\n\n概念\n\n## 框架\n\n框架\n\n## 正文\n\n正文内容\n",
            title="测试主题",
            stage=STAGE_CONTENT,
            created="2024-01-01T00:00:00",
            updated="2024-01-01T00:00:00",
        )
        write_note(draft_path, post)

        runner = CliRunner()
        mock_llm = MagicMock()
        mock_llm.structured_call.return_value = {"should_backfill": False, "items": []}

        with patch("lifebook.cli.load_config", return_value=cfg), \
             patch("lifebook.writer.LLMClient", return_value=mock_llm):
            result = runner.invoke(main, ["publish"])
            assert result.exit_code == 0
            assert "已发布" in result.output

    def test_status_command_no_draft(self, tmp_path):
        """status with no draft should show inactive."""
        cfg = make_cfg(tmp_path)
        runner = CliRunner()
        with patch("lifebook.cli.load_config", return_value=cfg):
            result = runner.invoke(main, ["writer-status"])
            assert result.exit_code == 0
            assert "未启动" in result.output
