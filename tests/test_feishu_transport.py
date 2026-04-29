"""Unit tests for feishu_transport.py."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from lifebook.config import FeishuConfig


@pytest.fixture
def cfg():
    return FeishuConfig(app_id="test-app", app_secret="test-secret")


@pytest.fixture
def transport(cfg):
    with patch("lifebook.feishu_transport.lark") as mock_lark:
        mock_client = MagicMock()
        mock_lark.Client.builder.return_value.app_id.return_value.app_secret.return_value.log_level.return_value.build.return_value = mock_client
        mock_lark.LogLevel.WARNING = "WARNING"
        from lifebook.feishu_transport import FeishuTransport
        t = FeishuTransport(cfg)
        t.api = mock_client
        return t


class TestSendText:
    def test_success(self, transport):
        resp = MagicMock()
        resp.success.return_value = True
        resp.data.message_id = "msg_123"
        transport.api.im.v1.message.create.return_value = resp

        result = transport.send_text("chat_abc", "hello")
        assert result == "msg_123"

    def test_failure_returns_none(self, transport):
        resp = MagicMock()
        resp.success.return_value = False
        resp.code = 10001
        resp.msg = "error"
        transport.api.im.v1.message.create.return_value = resp

        result = transport.send_text("chat_abc", "hello")
        assert result is None


class TestReplyText:
    def test_success(self, transport):
        resp = MagicMock()
        resp.success.return_value = True
        resp.data.message_id = "msg_reply"
        transport.api.im.v1.message.reply.return_value = resp

        result = transport.reply_text("msg_123", "reply text")
        assert result == "msg_reply"

    def test_failure_returns_none(self, transport):
        resp = MagicMock()
        resp.success.return_value = False
        resp.code = 10001
        resp.msg = "error"
        transport.api.im.v1.message.reply.return_value = resp

        result = transport.reply_text("msg_123", "reply text")
        assert result is None


class TestTenantToken:
    def test_success(self, transport):
        with patch("lifebook.feishu_transport.httpx") as mock_httpx:
            mock_resp = MagicMock()
            mock_resp.json.return_value = {"code": 0, "tenant_access_token": "tok_abc"}
            mock_httpx.post.return_value = mock_resp

            result = transport._tenant_token()
            assert result == "tok_abc"

    def test_failure_returns_none(self, transport):
        with patch("lifebook.feishu_transport.httpx") as mock_httpx:
            mock_resp = MagicMock()
            mock_resp.json.return_value = {"code": 10003, "msg": "invalid"}
            mock_httpx.post.return_value = mock_resp

            result = transport._tenant_token()
            assert result is None


class TestUploadFile:
    def test_success(self, transport):
        transport._tenant_token = MagicMock(return_value="tok_abc")
        with patch("lifebook.feishu_transport.httpx") as mock_httpx:
            mock_resp = MagicMock()
            mock_resp.json.return_value = {"code": 0, "data": {"file_key": "file_xyz"}}
            mock_httpx.post.return_value = mock_resp

            result = transport.upload_file(b"audio data", "test.mp3")
            assert result == "file_xyz"

    def test_token_failure_returns_none(self, transport):
        transport._tenant_token = MagicMock(return_value=None)
        result = transport.upload_file(b"data", "test.mp3")
        assert result is None

    def test_upload_failure_returns_none(self, transport):
        transport._tenant_token = MagicMock(return_value="tok_abc")
        with patch("lifebook.feishu_transport.httpx") as mock_httpx:
            mock_resp = MagicMock()
            mock_resp.json.return_value = {"code": 10001, "msg": "upload error"}
            mock_httpx.post.return_value = mock_resp

            result = transport.upload_file(b"data", "test.mp3")
            assert result is None

    def test_with_duration(self, transport):
        transport._tenant_token = MagicMock(return_value="tok_abc")
        with patch("lifebook.feishu_transport.httpx") as mock_httpx:
            mock_resp = MagicMock()
            mock_resp.json.return_value = {"code": 0, "data": {"file_key": "file_abc"}}
            mock_httpx.post.return_value = mock_resp

            result = transport.upload_file(b"data", "test.opus", file_type="opus", duration=10.5)
            assert result == "file_abc"
            call_kwargs = mock_httpx.post.call_args
            assert call_kwargs.kwargs["data"]["duration"] == "10500"


class TestSendAudio:
    def test_success(self, transport):
        resp = MagicMock()
        resp.success.return_value = True
        resp.data.message_id = "msg_audio"
        transport.api.im.v1.message.create.return_value = resp

        result = transport.send_audio("chat_abc", "file_key")
        assert result == "msg_audio"

    def test_failure_returns_none(self, transport):
        resp = MagicMock()
        resp.success.return_value = False
        resp.code = 10001
        resp.msg = "error"
        transport.api.im.v1.message.create.return_value = resp

        result = transport.send_audio("chat_abc", "file_key")
        assert result is None


class TestSendFile:
    def test_success(self, transport):
        resp = MagicMock()
        resp.success.return_value = True
        resp.data.message_id = "msg_file"
        transport.api.im.v1.message.create.return_value = resp

        result = transport.send_file("chat_abc", "file_key")
        assert result == "msg_file"

    def test_failure_returns_none(self, transport):
        resp = MagicMock()
        resp.success.return_value = False
        resp.code = 10001
        resp.msg = "error"
        transport.api.im.v1.message.create.return_value = resp

        result = transport.send_file("chat_abc", "file_key")
        assert result is None


class TestDownloadImageMessage:
    def test_success(self, transport):
        resp = MagicMock()
        resp.success.return_value = True
        resp.file.read.return_value = b"image bytes"
        transport.api.im.v1.message_resource.get.return_value = resp

        result = transport.download_image_message("msg_123", "img_key")
        assert result == b"image bytes"

    def test_failure_returns_none(self, transport):
        resp = MagicMock()
        resp.success.return_value = False
        resp.code = 10001
        resp.msg = "error"
        transport.api.im.v1.message_resource.get.return_value = resp

        result = transport.download_image_message("msg_123", "img_key")
        assert result is None

    def test_no_file_returns_none(self, transport):
        resp = MagicMock()
        resp.success.return_value = True
        resp.file = None
        transport.api.im.v1.message_resource.get.return_value = resp

        result = transport.download_image_message("msg_123", "img_key")
        assert result is None


class TestStop:
    def test_stop_with_ws_client(self, transport):
        transport._ws_client = MagicMock()
        transport.stop()
        transport._ws_client.close.assert_called_once()

    def test_stop_without_ws_client(self, transport):
        transport._ws_client = None
        transport.stop()  # should not raise
