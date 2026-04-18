"""Configuration loader."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = Path.home() / "Documents" / "Knowledge" / ".lifebook" / "config.yaml"


@dataclass
class KnowledgeConfig:
    root: Path
    sources_dir: str = "10-sources"
    topics_dir: str = "20-topics"
    trajectories_dir: str = "30-trajectories"
    state_dir: str = ".lifebook"
    publish_dir: str = "99-publish"

    @property
    def sources_path(self) -> Path:
        return self.root / self.sources_dir

    @property
    def topics_path(self) -> Path:
        return self.root / self.topics_dir

    @property
    def trajectories_path(self) -> Path:
        return self.root / self.trajectories_dir

    @property
    def state_path(self) -> Path:
        return self.root / self.state_dir

    @property
    def publish_path(self) -> Path:
        return self.root / self.publish_dir


@dataclass
class LLMConfig:
    provider: str = "anthropic"
    base_url: str = "https://api.anthropic.com"
    api_key: str = ""
    model: str = "claude-sonnet-4-5"
    digest_model: str = "claude-sonnet-4-5"
    max_tokens: int = 4096
    temperature: float = 0.3
    timeout: int = 120
    extra_headers: dict[str, str] = field(default_factory=dict)


@dataclass
class FeishuConfig:
    app_id: str = ""
    app_secret: str = ""
    digest_chat_id: str = ""


@dataclass
class ExecutorConfig:
    batch_limit: int = 20
    fetch_timeout: int = 30
    user_agent: str = "Mozilla/5.0 LifeBook/0.1"
    classify_min_confidence: float = 0.5


@dataclass
class DigestConfig:
    schedule: str = "23:30"
    include_anomalies: bool = True
    max_related_per_item: int = 3


@dataclass
class TavilyConfig:
    api_key: str = ""
    extract_depth: str = "advanced"
    timeout: int = 30


@dataclass
class FetchConfig:
    skip_domains: list[str] = field(default_factory=list)
    enable_fallback: bool = True
    user_agent: str = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) LifeBook/0.1"
    timeout: int = 30


@dataclass
class LoggingConfig:
    level: str = "INFO"
    retention_days: int = 30


@dataclass
class Config:
    knowledge: KnowledgeConfig
    llm: LLMConfig
    feishu: FeishuConfig
    executor: ExecutorConfig
    digest: DigestConfig
    tavily: TavilyConfig
    fetch: FetchConfig
    logging: LoggingConfig
    raw: dict[str, Any] = field(default_factory=dict)


def load_config(path: Path | str | None = None) -> Config:
    """Load configuration from YAML file."""
    cfg_path = Path(path) if path else Path(os.environ.get("LIFEBOOK_CONFIG", DEFAULT_CONFIG_PATH))
    if not cfg_path.exists():
        raise FileNotFoundError(
            f"Config file not found: {cfg_path}\n"
            f"Copy config.example.yaml to {cfg_path} and edit."
        )
    with cfg_path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    knowledge_raw = raw.get("knowledge", {})
    knowledge = KnowledgeConfig(
        root=Path(knowledge_raw.get("root", Path.home() / "Documents" / "Knowledge")).expanduser(),
        sources_dir=knowledge_raw.get("sources_dir", "10-sources"),
        topics_dir=knowledge_raw.get("topics_dir", "20-topics"),
        trajectories_dir=knowledge_raw.get("trajectories_dir", "30-trajectories"),
        state_dir=knowledge_raw.get("state_dir", ".lifebook"),
        publish_dir=knowledge_raw.get("publish_dir", "99-publish"),
    )

    def _filter(dc_cls, section):
        import dataclasses as _dc
        allowed = {f.name for f in _dc.fields(dc_cls)}
        return {k: v for k, v in (section or {}).items() if v is not None and k in allowed}

    llm = LLMConfig(**_filter(LLMConfig, raw.get("llm")))
    feishu = FeishuConfig(**_filter(FeishuConfig, raw.get("feishu")))
    executor = ExecutorConfig(**_filter(ExecutorConfig, raw.get("executor")))
    digest = DigestConfig(**_filter(DigestConfig, raw.get("digest")))
    tavily = TavilyConfig(**_filter(TavilyConfig, raw.get("tavily")))
    fetch = FetchConfig(**_filter(FetchConfig, raw.get("fetch")))
    logging_cfg = LoggingConfig(**_filter(LoggingConfig, raw.get("logging")))

    return Config(
        knowledge=knowledge,
        llm=llm,
        feishu=feishu,
        executor=executor,
        digest=digest,
        tavily=tavily,
        fetch=fetch,
        logging=logging_cfg,
        raw=raw,
    )
