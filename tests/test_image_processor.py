"""Tests for image_processor: compress, resize, encode."""
from __future__ import annotations

import io
from unittest.mock import patch

import pytest
from PIL import Image

from lifebook.config import ImageConfig
from lifebook.image_processor import ImageData, compress_image


def _make_jpeg(width: int = 100, height: int = 100) -> bytes:
    img = Image.new("RGB", (width, height), color=(128, 64, 32))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95)
    return buf.getvalue()


def _make_png_rgba(width: int = 100, height: int = 100) -> bytes:
    img = Image.new("RGBA", (width, height), color=(0, 128, 255, 200))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_png_rgb(width: int = 100, height: int = 100) -> bytes:
    img = Image.new("RGB", (width, height), color=(0, 128, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class TestCompressImage:
    def test_small_jpeg_unchanged_dimensions(self):
        data = _make_jpeg(100, 100)
        cfg = ImageConfig(max_long_edge=200, max_bytes=5_000_000, jpeg_quality=85)
        result = compress_image(data, cfg)
        assert isinstance(result, ImageData)
        assert result.width == 100
        assert result.height == 100
        assert result.media_type == "image/jpeg"
        assert len(result.base64_data) > 0

    def test_large_image_resized(self):
        data = _make_jpeg(3000, 2000)
        cfg = ImageConfig(max_long_edge=1568, max_bytes=5_000_000, jpeg_quality=85)
        result = compress_image(data, cfg)
        assert result.width <= 1568
        assert result.height <= 1568
        assert max(result.width, result.height) >= 1566

    def test_portrait_image_resized(self):
        data = _make_jpeg(800, 3200)
        cfg = ImageConfig(max_long_edge=1568, max_bytes=5_000_000, jpeg_quality=85)
        result = compress_image(data, cfg)
        assert result.height == 1568
        assert result.width <= 1568

    def test_png_with_alpha_preserved_as_png(self):
        data = _make_png_rgba(100, 100)
        cfg = ImageConfig(max_long_edge=200, max_bytes=5_000_000, jpeg_quality=85)
        result = compress_image(data, cfg)
        assert result.media_type == "image/png"

    def test_png_without_alpha_converted_to_jpeg(self):
        data = _make_png_rgb(100, 100)
        cfg = ImageConfig(max_long_edge=200, max_bytes=5_000_000, jpeg_quality=85)
        result = compress_image(data, cfg)
        assert result.media_type == "image/jpeg"

    def test_original_size_recorded(self):
        data = _make_jpeg(100, 100)
        cfg = ImageConfig(max_long_edge=200, max_bytes=5_000_000, jpeg_quality=85)
        result = compress_image(data, cfg)
        assert result.original_size == len(data)

    def test_compressed_size_recorded(self):
        data = _make_jpeg(100, 100)
        cfg = ImageConfig(max_long_edge=200, max_bytes=5_000_000, jpeg_quality=85)
        result = compress_image(data, cfg)
        assert result.compressed_size > 0

    def test_compressed_size_within_limit(self):
        data = _make_jpeg(300, 300)
        cfg = ImageConfig(max_long_edge=300, max_bytes=50_000, jpeg_quality=85)
        result = compress_image(data, cfg)
        assert result.compressed_size <= cfg.max_bytes

    def test_raises_when_size_uncompressible(self):
        data = _make_png_rgba(100, 100)
        cfg = ImageConfig(max_long_edge=200, max_bytes=100, jpeg_quality=85)
        with pytest.raises(ValueError, match="Image too large after compression"):
            compress_image(data, cfg)

    def test_unsupported_format_raises(self):
        data = b"\x00\x01\x02\x03garbage"
        cfg = ImageConfig()
        with pytest.raises(Exception):
            compress_image(data, cfg)

    def test_base64_decodable(self):
        import base64
        data = _make_jpeg(50, 50)
        cfg = ImageConfig(max_long_edge=100, max_bytes=5_000_000, jpeg_quality=85)
        result = compress_image(data, cfg)
        decoded = base64.standard_b64decode(result.base64_data)
        assert len(decoded) == result.compressed_size

    def test_quality_reduced_when_too_large(self):
        data = _make_jpeg(400, 400)
        cfg = ImageConfig(max_long_edge=400, max_bytes=2_000, jpeg_quality=85)
        result = compress_image(data, cfg)
        assert result.compressed_size <= cfg.max_bytes
