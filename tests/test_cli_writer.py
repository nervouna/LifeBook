"""Tests for CLI write/publish commands."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from lifebook.cli import main
from lifebook.config import (
    Config, KnowledgeConfig, LLMConfig, FeishuConfig,
    ExecutorConfig, DigestConfig, TavilyConfig, FetchConfig, LoggingConfig,
)
from lifebook.writer import STAGE_CONTENT


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
        publish_dir = cfg.knowledge.publish_path
        publish_dir.mkdir(parents=True, exist_ok=True)
        meta = {
            "stage": STAGE_CONTENT,
            "title": "测试主题",
            "created": "2024-01-01T00:00:00",
            "updated": "2024-01-01T00:00:00",
            "checklist": "",
        }
        (publish_dir / "draft.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        (publish_dir / "draft.md").write_text("正文内容", encoding="utf-8")

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
