"""Unit tests for Feishu audio message sending."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from lifebook.feishu_transport import FeishuTransport


@pytest.fixture
def transport():
    cfg = MagicMock()
    cfg.app_id = "cli_test"
    cfg.app_secret = "secret_test"
    with patch("lifebook.feishu_transport.lark"):
        t = FeishuTransport(cfg)
    return transport_impl(t)


def transport_impl(t):
    """Helper to patch _tenant_token for tests."""
    t._tenant_token = MagicMock(return_value="fake_token")
    return t


class TestUploadAudio:
    def test_upload_returns_file_key(self, transport):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "code": 0,
            "data": {"file_key": "file_abc123"},
        }

        with patch("lifebook.feishu_transport.httpx.post", return_value=mock_resp):
            result = transport.upload_file(b"audio data", "podcast.opus", file_type="opus", duration=120)

        assert result == "file_abc123"

    def test_upload_failure_returns_none(self, transport):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"code": 234001, "msg": "invalid param"}

        with patch("lifebook.feishu_transport.httpx.post", return_value=mock_resp):
            result = transport.upload_file(b"data", "test.opus")

        assert result is None

    def test_upload_sends_correct_form_data(self, transport):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"code": 0, "data": {"file_key": "fk"}}

        with patch("lifebook.feishu_transport.httpx.post", return_value=mock_resp) as mock_post:
            transport.upload_file(b"opus_bytes", "ep.opus", file_type="opus", duration=60)

        call_kwargs = mock_post.call_args.kwargs
        assert call_kwargs["data"]["file_type"] == "opus"
        assert call_kwargs["data"]["duration"] == "60"
        assert "file" in call_kwargs["files"]

    def test_upload_without_duration(self, transport):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"code": 0, "data": {"file_key": "fk"}}

        with patch("lifebook.feishu_transport.httpx.post", return_value=mock_resp) as mock_post:
            transport.upload_file(b"data", "test.opus")

        call_kwargs = mock_post.call_args.kwargs
        assert "duration" not in call_kwargs["data"]


class TestSendAudio:
    def test_send_audio_calls_create_message(self, transport):
        mock_resp = MagicMock()
        mock_resp.success.return_value = True
        mock_resp.data = MagicMock(message_id="om_123")
        transport.api.im.v1.message.create = MagicMock(return_value=mock_resp)

        result = transport.send_audio("oc_chat123", "file_abc123")

        assert result == "om_123"

    def test_send_audio_failure_returns_none(self, transport):
        mock_resp = MagicMock()
        mock_resp.success.return_value = False
        mock_resp.code = 23045
        mock_resp.msg = "chat not found"
        transport.api.im.v1.message.create = MagicMock(return_value=mock_resp)

        result = transport.send_audio("oc_bad", "file_key")

        assert result is None

    def test_send_audio_uses_correct_msg_type(self, transport):
        mock_resp = MagicMock()
        mock_resp.success.return_value = True
        mock_resp.data = MagicMock(message_id="om_x")
        transport.api.im.v1.message.create = MagicMock(return_value=mock_resp)

        transport.send_audio("oc_chat", "file_key1")

        req = transport.api.im.v1.message.create.call_args[0][0]
        assert req.request_body.msg_type == "audio"
        assert "file_key1" in req.request_body.content


class TestTenantToken:
    def test_returns_token_on_success(self):
        cfg = MagicMock()
        cfg.app_id = "cli_x"
        cfg.app_secret = "sec_x"
        with patch("lifebook.feishu_transport.lark"):
            t = FeishuTransport(cfg)

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"code": 0, "tenant_access_token": "t-abc"}
        with patch("lifebook.feishu_transport.httpx.post", return_value=mock_resp):
            token = t._tenant_token()

        assert token == "t-abc"

    def test_returns_none_on_failure(self):
        cfg = MagicMock()
        cfg.app_id = "cli_x"
        cfg.app_secret = "sec_x"
        with patch("lifebook.feishu_transport.lark"):
            t = FeishuTransport(cfg)

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"code": 9999, "msg": "bad creds"}
        with patch("lifebook.feishu_transport.httpx.post", return_value=mock_resp):
            token = t._tenant_token()

        assert token is None
