"""MiMo TTS client: text-to-speech via OpenAI-compatible chat completions API."""
from __future__ import annotations

import base64
import logging

import httpx

from .config import TTSConfig

logger = logging.getLogger(__name__)


class TTSError(Exception):
    pass


class TTSClient:
    def __init__(self, cfg: TTSConfig):
        self.cfg = cfg

    def synthesize(self, text: str) -> bytes:
        """Convert text to audio bytes (mp3)."""
        if not text or not text.strip():
            raise ValueError("empty text")

        url = f"{self.cfg.base_url}/chat/completions"
        headers = {
            "api-key": self.cfg.api_key,
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.cfg.model,
            "messages": [
                {"role": "assistant", "content": text.strip()},
            ],
            "audio": {
                "format": self.cfg.format,
                "voice": self.cfg.voice_id,
            },
            "stream": False,
        }

        with httpx.Client(timeout=self.cfg.timeout) as http:
            resp = http.post(url, headers=headers, json=payload)

        if resp.status_code != 200:
            raise TTSError(f"TTS HTTP {resp.status_code}: {resp.text[:200]}")

        data = resp.json()

        audio_data = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("audio", {})
            .get("data")
        )
        if not audio_data:
            logger.error("TTS API response: %s", data)
            raise TTSError("TTS response contains no audio data")

        return base64.b64decode(audio_data)
