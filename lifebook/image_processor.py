"""Image preprocessing: resize, compress, and encode images for LLM input."""
from __future__ import annotations

import base64
import io
from dataclasses import dataclass

from PIL import Image

from .config import ImageConfig

_SUPPORTED_FORMATS = {"JPEG", "PNG", "GIF", "WEBP"}
_MEDIA_TYPE_MAP = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "GIF": "image/gif",
    "WEBP": "image/webp",
}
_MIME_TO_EXT = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
}


def detect_mime_type(image_bytes: bytes) -> str:
    """Detect the MIME type of raw image bytes using Pillow.

    Returns a media type string such as ``"image/jpeg"`` or
    ``"image/png"``.  Falls back to ``"image/jpeg"`` for unknown formats.
    """
    try:
        img = Image.open(io.BytesIO(image_bytes))
        fmt = img.format or "JPEG"
        return _MEDIA_TYPE_MAP.get(fmt, "image/jpeg")
    except (OSError, ValueError, KeyError):
        return "image/jpeg"


def ext_for_mime(mime_type: str) -> str:
    """Return file extension for a MIME type."""
    return _MIME_TO_EXT.get(mime_type.lower(), ".bin")


@dataclass
class ImageData:
    """Preprocessed image ready for LLM multimodal input."""

    base64_data: str
    media_type: str
    original_size: int
    compressed_size: int
    width: int
    height: int


def compress_image(image_bytes: bytes, cfg: ImageConfig) -> ImageData:
    """Resize and compress image bytes; return ImageData for LLM input."""
    original_size = len(image_bytes)

    img = Image.open(io.BytesIO(image_bytes))
    fmt = img.format or "JPEG"
    if fmt not in _SUPPORTED_FORMATS:
        raise ValueError(f"Unsupported image format: {fmt}")

    img = img.convert("RGB") if fmt != "PNG" or not _has_alpha(img) else img

    img = _resize(img, cfg.max_long_edge)
    width, height = img.size

    out_bytes, out_fmt = _compress(img, fmt, cfg)

    compressed_size = len(out_bytes)
    if compressed_size > cfg.max_bytes:
        raise ValueError(
            f"Image too large after compression: {compressed_size} bytes "
            f"(limit {cfg.max_bytes}). Consider a smaller image."
        )

    encoded = base64.standard_b64encode(out_bytes).decode("ascii")
    media_type = _MEDIA_TYPE_MAP.get(out_fmt, "image/jpeg")
    return ImageData(
        base64_data=encoded,
        media_type=media_type,
        original_size=original_size,
        compressed_size=compressed_size,
        width=width,
        height=height,
    )


def _has_alpha(img: Image.Image) -> bool:
    return img.mode in ("RGBA", "LA", "PA") or (
        img.mode == "P" and "transparency" in img.info
    )


def _resize(img: Image.Image, max_long_edge: int) -> Image.Image:
    w, h = img.size
    long_edge = max(w, h)
    if long_edge <= max_long_edge:
        return img
    scale = max_long_edge / long_edge
    new_w = max(1, int(w * scale))
    new_h = max(1, int(h * scale))
    return img.resize((new_w, new_h), Image.LANCZOS)


def _compress(img: Image.Image, fmt: str, cfg: ImageConfig) -> tuple[bytes, str]:
    """Try to compress below cfg.max_bytes using decreasing quality.

    For PNG with alpha, keeps PNG format (lossless). For other formats,
    converts to JPEG. Returns (bytes, format_name).
    """
    if fmt == "PNG" and _has_alpha(img):
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue(), "PNG"

    # Use JPEG for everything else
    out_img = img if img.mode == "RGB" else img.convert("RGB")
    quality = cfg.jpeg_quality
    while quality >= 1:
        buf = io.BytesIO()
        out_img.save(buf, format="JPEG", quality=quality, optimize=True)
        data = buf.getvalue()
        if len(data) <= cfg.max_bytes:
            return data, "JPEG"
        quality -= 10
    buf = io.BytesIO()
    out_img.save(buf, format="JPEG", quality=1, optimize=True)
    return buf.getvalue(), "JPEG"
