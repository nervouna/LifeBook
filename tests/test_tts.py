"""Unit tests for tts.py."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from lifebook.config import TTSConfig
from lifebook.tts import TTSClient, TTSError


@pytest.fixture
def tts_cfg():
    return TTSConfig(
        api_key="test-key",
        base_url="https://api.minimaxi.chat/v1",
        model="speech-2.8-hd",
        voice_id="Calm_Woman",
    )


@pytest.fixture
def client(tts_cfg):
    return TTSClient(tts_cfg)


class TestTTSClient:
    def test_synthesize_returns_bytes(self, client):
        fake_audio = b"\xff\xfb\x90\x00"  # fake mp3 header
        hex_audio = fake_audio.hex()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "base_resp": {"status_code": 0, "status_msg": "success"},
            "data": {"audio": hex_audio, "status": 2},
            "extra_info": {"audio_length": 1500, "audio_format": "mp3"},
        }

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
            "base_resp": {"status_code": 1000, "status_msg": "invalid api key"},
        }

        with patch("lifebook.tts.httpx.Client") as mock_cls:
            mock_cls.return_value.__enter__ = MagicMock(
                return_value=MagicMock(post=MagicMock(return_value=mock_resp))
            )
            mock_cls.return_value.__exit__ = MagicMock(return_value=False)
            with pytest.raises(TTSError, match="invalid api key"):
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
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "base_resp": {"status_code": 0, "status_msg": "success"},
            "data": {"audio": "abcd", "status": 2},
        }

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
        assert payload["model"] == "speech-2.8-hd"
        assert payload["text"] == "Test text"
        assert payload["voice_setting"]["voice_id"] == "Calm_Woman"

    def test_synthesize_custom_voice_and_speed(self, tts_cfg):
        tts_cfg.voice_id = "Deep_Voice_Man"
        tts_cfg.speed = 1.5
        client = TTSClient(tts_cfg)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "base_resp": {"status_code": 0, "status_msg": "success"},
            "data": {"audio": "abcd", "status": 2},
        }

        with patch("lifebook.tts.httpx.Client") as mock_cls:
            mock_post = MagicMock(return_value=mock_resp)
            mock_cls.return_value.__enter__ = MagicMock(
                return_value=MagicMock(post=mock_post)
            )
            mock_cls.return_value.__exit__ = MagicMock(return_value=False)
            client.synthesize("Test")

        call_kwargs = mock_post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert payload["voice_setting"]["voice_id"] == "Deep_Voice_Man"
        assert payload["voice_setting"]["speed"] == 1.5

    def test_synthesize_empty_text_raises(self, client):
        with pytest.raises(ValueError, match="empty"):
            client.synthesize("")

    def test_synthesize_no_audio_in_response(self, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "base_resp": {"status_code": 0, "status_msg": "success"},
            "data": {"status": 1},  # still synthesizing
        }

        with patch("lifebook.tts.httpx.Client") as mock_cls:
            mock_cls.return_value.__enter__ = MagicMock(
                return_value=MagicMock(post=MagicMock(return_value=mock_resp))
            )
            mock_cls.return_value.__exit__ = MagicMock(return_value=False)
            with pytest.raises(TTSError, match="no audio"):
                client.synthesize("Hello")
