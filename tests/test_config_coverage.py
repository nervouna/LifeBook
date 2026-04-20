"""Coverage tests for config.py missing lines (load_config)."""
from __future__ import annotations

from pathlib import Path

import pytest

from lifebook.config import load_config, KnowledgeConfig


class TestLoadConfig:
    def test_loads_yaml(self, tmp_path: Path):
        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text(
            "knowledge:\n  root: /tmp/kb\n"
            "llm:\n  api_key: test-key\n  base_url: https://api.test\n"
            "feishu:\n  app_id: app123\n"
            "tavily:\n  api_key: tav123\n"
            "executor: {}\n"
            "digest: {}\n"
            "fetch: {}\n"
            "logging:\n  level: DEBUG\n",
            encoding="utf-8",
        )
        cfg = load_config(cfg_path)
        assert cfg.knowledge.root == Path("/tmp/kb")
        assert cfg.llm.api_key == "test-key"
        assert cfg.logging.level == "DEBUG"

    def test_missing_raises(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            load_config(tmp_path / "nope.yaml")

    def test_empty_yaml_defaults(self, tmp_path: Path):
        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text("", encoding="utf-8")
        cfg = load_config(cfg_path)
        assert cfg.llm.provider == "openai"
        assert cfg.executor.batch_limit == 20

    def test_env_var_config(self, tmp_path: Path, monkeypatch):
        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text("knowledge:\n  root: /tmp/kb\n", encoding="utf-8")
        monkeypatch.setenv("LIFEBOOK_CONFIG", str(cfg_path))
        cfg = load_config()
        assert cfg.knowledge.root == Path("/tmp/kb")

    def test_knowledge_paths(self, tmp_path: Path):
        cfg = KnowledgeConfig(root=tmp_path)
        assert cfg.sources_path == tmp_path / "10-sources"
        assert cfg.topics_path == tmp_path / "20-topics"
        assert cfg.state_path == tmp_path / ".lifebook"
        assert cfg.publish_path == tmp_path / "99-publish"
        assert cfg.trajectories_path == tmp_path / "30-trajectories"
