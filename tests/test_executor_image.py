"""Tests for executor image processing branch."""
from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from lifebook.config import ImageConfig
from lifebook.executor import Executor, ProcessResult
from lifebook.image_processor import ImageData


# ---------- fixtures ----------

@pytest.fixture
def mock_config(tmp_path):
    from lifebook.config import DEFAULT_CATEGORIES, VisionConfig
    sources = tmp_path / "10-sources"
    sources.mkdir()
    (sources / "images").mkdir()
    topics = tmp_path / "20-topics"
    topics.mkdir()
    state = tmp_path / ".lifebook"
    state.mkdir()

    cfg = MagicMock()
    cfg.knowledge.root = tmp_path
    cfg.knowledge.sources_path = sources
    cfg.knowledge.topics_path = topics
    cfg.knowledge.state_path = state
    cfg.knowledge.categories = list(DEFAULT_CATEGORIES)
    cfg.executor.classify_min_confidence = 0.5
    cfg.executor.batch_limit = 20
    cfg.image = ImageConfig()
    cfg.llm = MagicMock()
    cfg.llm.model = "test-model"
    cfg.vision = VisionConfig(model="vision-model", base_url="https://vision.api")
    cfg.tavily = MagicMock()
    cfg.fetch = MagicMock()
    return cfg


def _make_jpeg_bytes(w: int = 100, h: int = 100) -> bytes:
    img = Image.new("RGB", (w, h), color=(100, 150, 200))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def _write_image_source(
    sources_dir: Path,
    root: Path,
    filename: str,
    image_bytes: bytes,
    caption: str = "",
    **extra_meta,
) -> Path:
    images_dir = sources_dir / "images"
    images_dir.mkdir(exist_ok=True)
    img_file = images_dir / "testhash.jpg"
    img_file.write_bytes(image_bytes)
    rel = str(img_file.relative_to(root))

    path = sources_dir / filename
    lines = [
        "---",
        "source_type: image",
        "status: inbox",
        f"image_path: {rel}",
        "image_hash: testhash",
        "image_mime: image/jpeg",
    ]
    for k, v in extra_meta.items():
        lines.append(f"{k}: {v}")
    lines.append("---")
    lines.append(caption)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def executor(mock_config):
    from lifebook.store import NoteStore
    store = NoteStore(mock_config.knowledge)
    llm = MagicMock()
    vision_llm = MagicMock()
    fetcher = MagicMock()
    exec = Executor(mock_config, store=store, llm=llm, fetcher=fetcher)
    exec.vision_llm = vision_llm
    return exec


def _good_extracted():
    from lifebook.config import DEFAULT_CATEGORIES
    return {
        "title": "Image Note",
        "summary": "A test summary.",
        "key_points": ["point 1", "point 2"],
        "narrative": "Some narrative.",
        "tags": ["资讯", "AI技术"],
        "category": DEFAULT_CATEGORIES[0],
        "related_keywords": ["AI", "test"],
        "confidence": 0.9,
    }


class TestProcessImageFile:
    def test_success(self, executor, mock_config):
        jpeg = _make_jpeg_bytes()
        path = _write_image_source(
            mock_config.knowledge.sources_path,
            mock_config.knowledge.root,
            "img-test.md",
            jpeg,
        )
        executor.vision_llm.structured_call.return_value = _good_extracted()
        result = executor.process_file(path)
        assert result.ok
        assert result.topic_path is not None

    def test_uses_vision_llm_client(self, executor, mock_config):
        jpeg = _make_jpeg_bytes()
        path = _write_image_source(
            mock_config.knowledge.sources_path,
            mock_config.knowledge.root,
            "img-vision.md",
            jpeg,
        )
        executor.vision_llm.structured_call.return_value = _good_extracted()
        executor.process_file(path)
        executor.vision_llm.structured_call.assert_called_once()
        executor.llm.structured_call.assert_not_called()

    def test_images_passed_to_llm(self, executor, mock_config):
        jpeg = _make_jpeg_bytes()
        path = _write_image_source(
            mock_config.knowledge.sources_path,
            mock_config.knowledge.root,
            "img-imgparam.md",
            jpeg,
        )
        executor.vision_llm.structured_call.return_value = _good_extracted()
        executor.process_file(path)
        call_kwargs = executor.vision_llm.structured_call.call_args.kwargs
        images = call_kwargs.get("images")
        assert images is not None
        assert len(images) == 1
        assert isinstance(images[0], ImageData)

    def test_missing_image_path_meta(self, executor, mock_config):
        path = mock_config.knowledge.sources_path / "no-imgpath.md"
        path.write_text(
            "---\nsource_type: image\nstatus: inbox\n---\n",
            encoding="utf-8",
        )
        result = executor.process_file(path)
        assert not result.ok
        assert "missing image_path" in result.error

    def test_image_file_not_found(self, executor, mock_config):
        path = mock_config.knowledge.sources_path / "img-missing.md"
        path.write_text(
            "---\nsource_type: image\nstatus: inbox\nimage_path: 10-sources/images/nonexistent.jpg\n---\n",
            encoding="utf-8",
        )
        result = executor.process_file(path)
        assert not result.ok
        assert "not found" in result.error

    def test_compression_failure(self, executor, mock_config):
        bad_bytes = b"\x00\x01\x02garbage"
        path = _write_image_source(
            mock_config.knowledge.sources_path,
            mock_config.knowledge.root,
            "img-bad.md",
            bad_bytes,
        )
        result = executor.process_file(path)
        assert not result.ok
        assert "compression failed" in result.error

    def test_low_confidence_skipped(self, executor, mock_config):
        jpeg = _make_jpeg_bytes()
        path = _write_image_source(
            mock_config.knowledge.sources_path,
            mock_config.knowledge.root,
            "img-lowconf.md",
            jpeg,
        )
        low = _good_extracted()
        low["confidence"] = 0.1
        executor.vision_llm.structured_call.return_value = low
        result = executor.process_file(path)
        assert not result.ok
        assert result.skipped_reason is not None

    def test_llm_failure_returns_error(self, executor, mock_config):
        jpeg = _make_jpeg_bytes()
        path = _write_image_source(
            mock_config.knowledge.sources_path,
            mock_config.knowledge.root,
            "img-llmfail.md",
            jpeg,
        )
        executor.vision_llm.structured_call.side_effect = RuntimeError("LLM timeout")
        result = executor.process_file(path)
        assert not result.ok
        assert "LLM failed" in result.error

    def test_caption_included_in_prompt(self, executor, mock_config):
        jpeg = _make_jpeg_bytes()
        path = _write_image_source(
            mock_config.knowledge.sources_path,
            mock_config.knowledge.root,
            "img-caption.md",
            jpeg,
            caption="this is my test caption",
        )
        executor.vision_llm.structured_call.return_value = _good_extracted()
        executor.process_file(path)
        call_kwargs = executor.vision_llm.structured_call.call_args.kwargs
        assert "test caption" in call_kwargs.get("user_prompt", "")

    def test_fallback_to_default_llm_when_vision_not_configured(self, mock_config, tmp_path):
        from lifebook.store import NoteStore
        mock_config.vision = None
        store = NoteStore(mock_config.knowledge)
        llm = MagicMock()
        fetcher = MagicMock()
        executor = Executor(mock_config, store=store, llm=llm, fetcher=fetcher)

        jpeg = _make_jpeg_bytes()
        path = _write_image_source(
            mock_config.knowledge.sources_path,
            mock_config.knowledge.root,
            "img-fallback.md",
            jpeg,
        )
        llm.structured_call.return_value = _good_extracted()
        executor.process_file(path)
        llm.structured_call.assert_called_once()
        assert executor.vision_llm is None

    def test_text_source_still_uses_text_path(self, executor, mock_config):
        path = mock_config.knowledge.sources_path / "text-note.md"
        path.write_text(
            "---\nsource_type: chat_note\nstatus: inbox\n---\nsome text content\n",
            encoding="utf-8",
        )
        executor.llm.structured_call.return_value = _good_extracted()
        result = executor.process_file(path)
        call_kwargs = executor.llm.structured_call.call_args.kwargs
        assert call_kwargs.get("images") is None
