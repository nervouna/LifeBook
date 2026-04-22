"""Configuration loader."""
from __future__ import annotations

import dataclasses
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from platformdirs import user_config_dir

DEFAULT_CONFIG_PATH = Path.home() / "Documents" / "Knowledge" / ".lifebook" / "config.yaml"
APP_CONFIG_DIR = Path(user_config_dir("lifebook"))
POINTER_FILE = APP_CONFIG_DIR / "location"


DEFAULT_CATEGORIES = [
    "AI技术",
    "开发者工具",
    "半导体",
    "消费电子",
    "媒体生态",
    "组织与劳动",
    "科技监管",
    "经济与产业",
]


@dataclass
class KnowledgeConfig:
    root: Path
    sources_dir: str = "10-sources"
    topics_dir: str = "20-topics"
    trajectories_dir: str = "30-trajectories"
    state_dir: str = ".lifebook"
    publish_dir: str = "99-publish"
    categories: list[str] = field(default_factory=lambda: list(DEFAULT_CATEGORIES))

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
    base_url: str = "https://api.deepseek.com"
    api_key: str = ""
    model: str = "deepseek-chat"
    digest_model: str = "deepseek-chat"
    max_tokens: int = 4096
    temperature: float = 0.3
    timeout: int = 120
    extra_headers: dict[str, str] = field(default_factory=dict)


@dataclass
class VisionConfig:
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    max_tokens: int = 4096
    temperature: float = 0.3
    timeout: int = 120
    extra_headers: dict[str, str] = field(default_factory=dict)


@dataclass
class ImageConfig:
    max_long_edge: int = 1568
    max_bytes: int = 1_048_576
    jpeg_quality: int = 85


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
class TTSConfig:
    api_key: str = ""
    base_url: str = "https://api.minimaxi.com/v1"
    model: str = "speech-2.8-hd"
    voice_id: str = "Calm_Woman"
    speed: float = 1.0
    volume: float = 1.0
    format: str = "mp3"
    timeout: int = 60


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
    image: ImageConfig = field(default_factory=ImageConfig)
    vision: VisionConfig | None = None
    tts: TTSConfig = field(default_factory=TTSConfig)
    raw: dict[str, Any] = field(default_factory=dict)


def _filter(dc_cls, section):
    allowed = {f.name for f in dataclasses.fields(dc_cls)}
    return {k: v for k, v in (section or {}).items() if v is not None and k in allowed}


def resolve_config_path(explicit: Path | str | None = None) -> Path:
    """Resolve config file path via: explicit arg → env var → pointer file → default."""
    if explicit:
        return Path(explicit)
    env = os.environ.get("LIFEBOOK_CONFIG")
    if env:
        return Path(env)
    try:
        kb_root = Path(POINTER_FILE.read_text(encoding="utf-8").strip())
        return kb_root / ".lifebook" / "config.yaml"
    except FileNotFoundError:
        return DEFAULT_CONFIG_PATH


def load_config(path: Path | str | None = None) -> Config:
    """Load configuration from YAML file."""
    cfg_path = resolve_config_path(path)
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
        categories=knowledge_raw.get("categories", list(DEFAULT_CATEGORIES)),
    )

    llm = LLMConfig(**_filter(LLMConfig, raw.get("llm")))
    feishu = FeishuConfig(**_filter(FeishuConfig, raw.get("feishu")))
    executor = ExecutorConfig(**_filter(ExecutorConfig, raw.get("executor")))
    digest = DigestConfig(**_filter(DigestConfig, raw.get("digest")))
    tavily = TavilyConfig(**_filter(TavilyConfig, raw.get("tavily")))
    fetch = FetchConfig(**_filter(FetchConfig, raw.get("fetch")))
    logging_cfg = LoggingConfig(**_filter(LoggingConfig, raw.get("logging")))
    image = ImageConfig(**_filter(ImageConfig, raw.get("image")))
    vision_raw = raw.get("vision")
    vision = VisionConfig(**_filter(VisionConfig, vision_raw)) if vision_raw else None
    tts = TTSConfig(**_filter(TTSConfig, raw.get("tts")))

    return Config(
        knowledge=knowledge,
        llm=llm,
        feishu=feishu,
        executor=executor,
        digest=digest,
        tavily=tavily,
        fetch=fetch,
        logging=logging_cfg,
        image=image,
        vision=vision,
        tts=tts,
        raw=raw,
    )
