"""End-to-end tests covering core business flows.

All tests use real file I/O with tmp_path, mock only external APIs (LLM, TTS, Tavily).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from lifebook.cli import main
from lifebook.config import (
    Config, KnowledgeConfig, LLMConfig, FeishuConfig,
    ExecutorConfig, DigestConfig, TavilyConfig, FetchConfig, LoggingConfig,
    TTSConfig, ImageConfig,
)
from lifebook.notes import new_post, write_note, read_note
from lifebook.writer import Writer, STAGE_CONCEPT, STAGE_FRAMEWORK, STAGE_CONTENT, STAGE_REVIEW


# ── fixtures ─────────────────────────────────────────────────────────


def make_config(kb: Path) -> Config:
    return Config(
        knowledge=KnowledgeConfig(root=kb),
        llm=LLMConfig(api_key="test-key", base_url="https://test.api"),
        feishu=FeishuConfig(),
        executor=ExecutorConfig(),
        digest=DigestConfig(),
        tavily=TavilyConfig(api_key="test-tavily"),
        fetch=FetchConfig(),
        logging=LoggingConfig(),
        tts=TTSConfig(api_key="test-tts", base_url="https://tts.test"),
        image=ImageConfig(),
    )


@pytest.fixture
def kb(tmp_path):
    """Create a minimal knowledge base directory structure."""
    root = tmp_path / "knowledge"
    root.mkdir()
    (root / "10-sources").mkdir()
    (root / "20-topics").mkdir()
    (root / "30-trajectories").mkdir()
    (root / "99-publish").mkdir()
    (root / ".lifebook").mkdir()
    return root


@pytest.fixture
def cfg(kb):
    return make_config(kb)


@pytest.fixture
def runner():
    return CliRunner()


# ── LLM response fixtures ───────────────────────────────────────────

EXTRACT_RESULT = {
    "title": "AI 编程助手的崛起",
    "summary": "AI 编程助手正在改变软件开发方式。",
    "key_points": "- GitHub Copilot 用户突破百万\n- 代码补全准确率提升至 60%",
    "narrative": "AI 编程助手正在从实验工具走向主流开发流程。",
    "tags": ["AI技术", "编程助手", "Copilot"],
    "category": "AI技术",
    "related_keywords": ["Copilot", "代码补全"],
    "confidence": 0.9,
}

CONCEPT_RESULT = {
    "topic": "AI 对创意工作的影响",
    "thesis": "AI 不会取代创意工作者，但会改变工作方式",
    "audience": "创意行业从业者",
    "concept_text": "本文探讨 AI 工具如何辅助而非替代创意过程。",
}

FRAMEWORK_RESULT = {
    "frameworks": [
        {
            "name": "方案A：影响分析",
            "outline": [
                {"heading": "现状", "point": "AI 工具在创意领域的应用现状"},
                {"heading": "影响", "point": "对工作流程和就业的双重影响"},
            ],
        },
    ]
}

BACKFILL_NONE = {"should_backfill": False, "items": []}


# ═══════════════════════════════════════════════════════════════════
# Flow 1: init → doctor
# ═══════════════════════════════════════════════════════════════════


class TestInitDoctorFlow:
    def test_init_creates_structure(self, runner, tmp_path):
        root = tmp_path / "new_kb"
        with patch("lifebook.cli.load_config") as mock_load:
            mock_load.return_value = make_config(root)
            result = runner.invoke(main, ["init", "--root", str(root)], catch_exceptions=False)

        assert result.exit_code == 0
        assert root.exists()
        assert (root / "10-sources").exists()
        assert (root / "20-topics").exists()
        assert (root / "99-publish").exists()
        assert (root / ".lifebook").exists()

    def test_doctor_checks_config(self, runner, cfg, kb):
        cfg_dir = kb / ".lifebook"
        cfg_dir.mkdir(exist_ok=True)
        (cfg_dir / "config.yaml").write_text(
            "knowledge:\n  root: /tmp/test\nllm:\n  api_key: test\n",
            encoding="utf-8",
        )
        with patch("lifebook.cli.load_config", return_value=cfg):
            result = runner.invoke(main, ["doctor"], catch_exceptions=False)
        assert result.exit_code == 0
        assert "Config" in result.output or "root" in result.output


# ═══════════════════════════════════════════════════════════════════
# Flow 2: ingest text → process --file → topic note
# ═══════════════════════════════════════════════════════════════════


class TestIngestProcessFlow:
    def test_ingest_text_then_process(self, runner, cfg, kb):
        """Ingest a text note, then process it into a topic note."""
        # Step 1: ingest text
        with patch("lifebook.cli.load_config", return_value=cfg):
            result = runner.invoke(
                main, ["ingest", "AI 编程助手正在改变开发方式。", "--type", "chat_note"],
                catch_exceptions=False,
            )
        assert result.exit_code == 0
        assert "Ingested" in result.output

        sources = list((kb / "10-sources").glob("*.md"))
        assert len(sources) == 1
        inbox_post = read_note(sources[0])
        assert inbox_post.get("status") == "inbox"
        assert "AI 编程助手" in inbox_post.content

        # Step 2: process the inbox file
        mock_llm = MagicMock()
        mock_llm.structured_call.return_value = EXTRACT_RESULT

        with patch("lifebook.cli.load_config", return_value=cfg), \
             patch("lifebook.executor.LLMClient", return_value=mock_llm):
            result = runner.invoke(
                main, ["process", "--file", str(sources[0])],
                catch_exceptions=False,
            )
        assert result.exit_code == 0

        topic_files = list((kb / "20-topics").rglob("*.md"))
        assert len(topic_files) >= 1
        topic = read_note(topic_files[0])
        assert topic.get("title") == "AI 编程助手的崛起"
        assert topic.get("category") == "AI技术"
        assert topic.get("status") == "active"

        source_post = read_note(sources[0])
        assert source_post.get("status") == "processed"

    def test_ingest_url_then_process(self, runner, cfg, kb):
        """Ingest a URL, mock fetch + LLM, process into topic."""
        with patch("lifebook.cli.load_config", return_value=cfg):
            result = runner.invoke(
                main, ["ingest", "https://example.com/ai-article"],
                catch_exceptions=False,
            )
        assert result.exit_code == 0

        sources = list((kb / "10-sources").glob("*.md"))
        assert len(sources) == 1

        mock_llm = MagicMock()
        mock_llm.structured_call.return_value = EXTRACT_RESULT

        from lifebook.fetcher import FetchResult
        mock_fetcher = MagicMock()
        mock_fetcher.fetch.return_value = FetchResult(
            ok=True, status="ok", content="Fetched article content about AI.",
            url="https://example.com/ai-article",
        )

        with patch("lifebook.cli.load_config", return_value=cfg), \
             patch("lifebook.executor.LLMClient", return_value=mock_llm), \
             patch("lifebook.executor.Fetcher", return_value=mock_fetcher):
            result = runner.invoke(
                main, ["process", "--file", str(sources[0])],
                catch_exceptions=False,
            )
        assert result.exit_code == 0

        topic_files = list((kb / "20-topics").rglob("*.md"))
        assert len(topic_files) >= 1


# ═══════════════════════════════════════════════════════════════════
# Flow 3: Writer — concept → framework → content → discuss → publish
# ═══════════════════════════════════════════════════════════════════


class TestWriterFlow:
    def test_full_writing_cycle(self, cfg, kb):
        """Complete writing cycle through Writer class with mocked LLM."""
        mock_llm = MagicMock()
        mock_llm.structured_call.side_effect = [
            CONCEPT_RESULT,     # start → concept
            FRAMEWORK_RESULT,   # confirm → framework
            BACKFILL_NONE,      # publish → backfill eval
        ]
        mock_llm.text_call.side_effect = [
            "## 现状\n\nAI 工具遍地开花。",   # section 1
            "## 影响\n\n工作流程被重塑。",     # section 2
            "- 检查数据来源\n- 验证结论",      # checklist
        ]
        mock_llm.agentic_call.return_value = "已根据反馈修改了引言部分。"

        w = Writer(cfg, mock_llm)

        # Step 1: start → concept stage
        result = w.start("我想写关于AI对创意工作的影响")
        assert w.active
        assert w.stage == STAGE_CONCEPT
        assert "核心概念" in result

        # Step 2: confirm → framework stage
        result = w.handle_message("确认，概念很好")
        assert w.stage == STAGE_FRAMEWORK
        assert "方案" in result

        # Step 3: pick framework → content stage
        result = w.handle_message("选方案1")
        assert w.stage == STAGE_CONTENT
        assert "现状" in result

        # Step 4: discuss → review stage
        result = w.handle_message("请修改引言")
        assert w.stage == STAGE_REVIEW
        assert "修改了引言" in result

        # Step 5: publish
        result = w.publish(force=True)
        assert "已发布" in result
        assert not w.active

        # Verify published file
        pub_files = list((kb / "99-publish").glob("*.md"))
        assert len(pub_files) == 1
        pub = read_note(pub_files[0])
        assert pub.get("title") == "AI 对创意工作的影响"
        assert pub.get("status") == "published"

        # Verify draft was cleaned up
        assert not (kb / "99-publish" / "draft.json").exists()
        assert not (kb / "99-publish" / "draft.md").exists()

    def test_writer_rejects_second_start(self, cfg):
        """Cannot start a new writing session while one is active."""
        mock_llm = MagicMock()
        mock_llm.structured_call.return_value = CONCEPT_RESULT

        w = Writer(cfg, mock_llm)
        w.start("idea1")
        assert w.active

        result = w.start("idea2")
        assert "已有一篇草稿" in result
        assert w.stage == STAGE_CONCEPT


# ═══════════════════════════════════════════════════════════════════
# Flow 4: index → search
# ═══════════════════════════════════════════════════════════════════


class TestIndexSearchFlow:
    def test_index_and_search(self, runner, cfg, kb):
        """Create topic notes, build index, then search."""
        for title, cat in [
            ("AI 编程助手", "AI技术"),
            ("芯片制造工艺", "半导体"),
            ("内容分发平台", "媒体生态"),
        ]:
            topic_dir = kb / "20-topics" / cat
            topic_dir.mkdir(parents=True, exist_ok=True)
            post = new_post(
                f"这是关于{title}的笔记内容。\n",
                title=title, category=cat, status="active",
            )
            write_note(topic_dir / f"{title}.md", post)

        mock_vi = MagicMock()
        mock_vi.incremental_update.return_value = {
            "upserted": 3, "deleted": 0, "unchanged": 0, "errors": 0,
        }

        with patch("lifebook.cli.load_config", return_value=cfg), \
             patch("lifebook.indexer.VectorIndex", return_value=mock_vi):
            result = runner.invoke(main, ["index"], catch_exceptions=False)
        assert result.exit_code == 0
        assert "Upserted: 3" in result.output

        from types import SimpleNamespace
        mock_vi.search.return_value = [
            SimpleNamespace(
                doc_id="20-topics/AI技术/AI 编程助手.md",
                distance=0.1,
                metadata={"title": "AI 编程助手"},
                text="这是关于AI 编程助手的笔记内容。",
            ),
        ]

        with patch("lifebook.cli.load_config", return_value=cfg), \
             patch("lifebook.vector.VectorIndex", return_value=mock_vi):
            result = runner.invoke(main, ["search", "编程助手"], catch_exceptions=False)
        assert result.exit_code == 0
        assert "AI 编程助手" in result.output


# ═══════════════════════════════════════════════════════════════════
# Flow 5: podcast — note → script → audio
# ═══════════════════════════════════════════════════════════════════


class TestPodcastFlow:
    def test_podcast_from_note(self, runner, cfg, kb):
        topic_dir = kb / "20-topics" / "AI技术"
        topic_dir.mkdir(parents=True, exist_ok=True)
        note_path = topic_dir / "AI 编程助手.md"
        post = new_post(
            "AI 编程助手正在改变软件开发方式。\n",
            title="AI 编程助手", category="AI技术", status="active",
        )
        write_note(note_path, post)

        mock_gen = MagicMock()
        mock_gen.generate.return_value = (b"fake_mp3_audio_bytes", 45)

        with patch("lifebook.cli.load_config", return_value=cfg), \
             patch("lifebook.podcast.PodcastGenerator", return_value=mock_gen):
            out_path = kb / "podcast_out.mp3"
            result = runner.invoke(
                main, ["podcast", str(note_path), "-o", str(out_path)],
                catch_exceptions=False,
            )

        assert result.exit_code == 0
        assert "Generating podcast" in result.output
        assert out_path.exists()
        assert out_path.read_bytes() == b"fake_mp3_audio_bytes"


# ═══════════════════════════════════════════════════════════════════
# Flow 6: recover — stale file rollback
# ═══════════════════════════════════════════════════════════════════


class TestRecoverFlow:
    def test_recover_stale_files(self, runner, cfg, kb):
        stale = kb / "10-sources" / "stale.md"
        post = new_post(
            "some content",
            source_type="chat_note", status="processing",
            created="2020-01-01T00:00:00",
        )
        write_note(stale, post)

        with patch("lifebook.cli.load_config", return_value=cfg):
            result = runner.invoke(main, ["recover"], catch_exceptions=False)

        assert result.exit_code == 0
        assert "Recovered" in result.output

        recovered_post = read_note(stale)
        assert recovered_post.get("status") == "inbox"
