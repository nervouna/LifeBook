"""MiniMax TTS client: text-to-speech via T2A HTTP API."""
from __future__ import annotations

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

        url = f"{self.cfg.base_url}/t2a_v2"
        headers = {
            "Authorization": f"Bearer {self.cfg.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.cfg.model,
            "text": text.strip(),
            "stream": False,
            "output_format": "hex",
            "voice_setting": {
                "voice_id": self.cfg.voice_id,
                "speed": self.cfg.speed,
                "vol": self.cfg.volume,
            },
            "audio_setting": {
                "format": self.cfg.format,
                "channel": 1,
            },
        }

        with httpx.Client(timeout=self.cfg.timeout) as http:
            resp = http.post(url, headers=headers, json=payload)

        if resp.status_code != 200:
            raise TTSError(f"TTS HTTP {resp.status_code}: {resp.text[:200]}")

        data = resp.json()
        base = data.get("base_resp", {})
        if base.get("status_code", -1) != 0:
            logger.error("TTS API response: %s", data)
            raise TTSError(f"TTS API error: {base.get('status_msg', 'unknown')}")

        audio_hex = data.get("data", {}).get("audio")
        if not audio_hex:
            raise TTSError("TTS response contains no audio data")

        return bytes.fromhex(audio_hex)
