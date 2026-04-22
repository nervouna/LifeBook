"""Unit tests for tts.py."""
from __future__ import annotations

import base64
from unittest.mock import MagicMock, patch

import pytest

from lifebook.config import TTSConfig
from lifebook.tts import TTSClient, TTSError


@pytest.fixture
def tts_cfg():
    return TTSConfig(
        api_key="test-key",
        base_url="https://api.xiaomimimo.com/v1",
        model="mimo-v2.5-tts",
        voice_id="mimo_default",
    )


@pytest.fixture
def client(tts_cfg):
    return TTSClient(tts_cfg)


def _mimo_response(audio_bytes: bytes) -> dict:
    """Build a MiMo TTS success response dict."""
    return {
        "choices": [
            {
                "message": {
                    "audio": {
                        "data": base64.b64encode(audio_bytes).decode(),
                    },
                },
            },
        ],
    }


class TestTTSClient:
    def test_synthesize_returns_bytes(self, client):
        fake_audio = b"\xff\xfb\x90\x00"  # fake mp3 header

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _mimo_response(fake_audio)

        with patch("lifebook.tts.httpx.Client") as mock_cls:
            mock_cls.return_value.__enter__ = MagicMock(
                return_value=MagicMock(post=MagicMock(return_value=mock_resp))
            )
            mock_cls.return_value.__exit__ = MagicMock(return_value=False)
            result = client.synthesize("Hello world")

        assert result == fake_audio

    def test_synthesize_api_error_raises(self, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "error": {"message": "invalid api key", "type": "auth_error"},
        }

        with patch("lifebook.tts.httpx.Client") as mock_cls:
            mock_cls.return_value.__enter__ = MagicMock(
                return_value=MagicMock(post=MagicMock(return_value=mock_resp))
            )
            mock_cls.return_value.__exit__ = MagicMock(return_value=False)
            with pytest.raises(TTSError, match="no audio"):
                client.synthesize("Hello")

    def test_synthesize_http_error_raises(self, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_resp.text = "rate limited"

        with patch("lifebook.tts.httpx.Client") as mock_cls:
            mock_cls.return_value.__enter__ = MagicMock(
                return_value=MagicMock(post=MagicMock(return_value=mock_resp))
            )
            mock_cls.return_value.__exit__ = MagicMock(return_value=False)
            with pytest.raises(TTSError, match="429"):
                client.synthesize("Hello")

    def test_synthesize_uses_correct_payload(self, client):
        fake_audio = b"\x00\x01"

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _mimo_response(fake_audio)

        with patch("lifebook.tts.httpx.Client") as mock_cls:
            mock_post = MagicMock(return_value=mock_resp)
            mock_cls.return_value.__enter__ = MagicMock(
                return_value=MagicMock(post=mock_post)
            )
            mock_cls.return_value.__exit__ = MagicMock(return_value=False)
            client.synthesize("Test text")

        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert payload["model"] == "mimo-v2.5-tts"
        assert payload["messages"] == [{"role": "assistant", "content": "Test text"}]
        assert payload["audio"]["voice"] == "mimo_default"
        assert payload["audio"]["format"] == "mp3"

    def test_synthesize_custom_voice_and_speed(self, tts_cfg):
        tts_cfg.voice_id = "custom_voice"
        client = TTSClient(tts_cfg)

        fake_audio = b"\x00\x01"

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _mimo_response(fake_audio)

        with patch("lifebook.tts.httpx.Client") as mock_cls:
            mock_post = MagicMock(return_value=mock_resp)
            mock_cls.return_value.__enter__ = MagicMock(
                return_value=MagicMock(post=mock_post)
            )
            mock_cls.return_value.__exit__ = MagicMock(return_value=False)
            client.synthesize("Test")

        call_kwargs = mock_post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert payload["audio"]["voice"] == "custom_voice"

    def test_synthesize_empty_text_raises(self, client):
        with pytest.raises(ValueError, match="empty"):
            client.synthesize("")

    def test_synthesize_no_audio_in_response(self, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [{"message": {}}],
        }

        with patch("lifebook.tts.httpx.Client") as mock_cls:
            mock_cls.return_value.__enter__ = MagicMock(
                return_value=MagicMock(post=MagicMock(return_value=mock_resp))
            )
            mock_cls.return_value.__exit__ = MagicMock(return_value=False)
            with pytest.raises(TTSError, match="no audio"):
                client.synthesize("Hello")

    def test_synthesize_uses_api_key_header(self, client):
        fake_audio = b"\x00\x01"

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _mimo_response(fake_audio)

        with patch("lifebook.tts.httpx.Client") as mock_cls:
            mock_post = MagicMock(return_value=mock_resp)
            mock_cls.return_value.__enter__ = MagicMock(
                return_value=MagicMock(post=mock_post)
            )
            mock_cls.return_value.__exit__ = MagicMock(return_value=False)
            client.synthesize("Test")

        call_kwargs = mock_post.call_args
        headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers")
        assert headers["api-key"] == "test-key"
        assert "Authorization" not in headers
