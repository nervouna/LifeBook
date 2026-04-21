"""Coverage tests for config.py missing lines (load_config)."""
from __future__ import annotations

from pathlib import Path

import pytest

from lifebook.config import load_config, KnowledgeConfig, resolve_config_path


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
        assert cfg.llm.base_url == "https://api.deepseek.com"
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


class TestDiscoverConfigPath:
    def test_explicit_takes_priority(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("LIFEBOOK_CONFIG", "/should/not/use/this.yaml")
        result = resolve_config_path(explicit=tmp_path / "explicit.yaml")
        assert result == tmp_path / "explicit.yaml"

    def test_env_var_when_no_explicit(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("LIFEBOOK_CONFIG", str(tmp_path / "env.yaml"))
        result = resolve_config_path()
        assert result == tmp_path / "env.yaml"

    def test_pointer_file_when_no_env(self, tmp_path: Path, monkeypatch):
        monkeypatch.delenv("LIFEBOOK_CONFIG", raising=False)
        kb_root = tmp_path / "my-kb"
        ptr_dir = tmp_path / "appcfg"
        ptr_file = ptr_dir / "location"
        ptr_dir.mkdir()
        ptr_file.write_text(str(kb_root), encoding="utf-8")

        import lifebook.config
        monkeypatch.setattr(lifebook.config, "POINTER_FILE", ptr_file)
        result = resolve_config_path()
        assert result == kb_root / ".lifebook" / "config.yaml"

    def test_default_when_nothing_set(self, tmp_path: Path, monkeypatch):
        monkeypatch.delenv("LIFEBOOK_CONFIG", raising=False)
        nonexistent = tmp_path / "nope" / "location"

        import lifebook.config
        monkeypatch.setattr(lifebook.config, "POINTER_FILE", nonexistent)
        result = resolve_config_path()
        from lifebook.config import DEFAULT_CONFIG_PATH
        assert result == DEFAULT_CONFIG_PATH
