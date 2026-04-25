"""Tests for Feishu image message routing."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


def _make_bot():
    from lifebook.feishu import FeishuBot
    bot = FeishuBot.__new__(FeishuBot)
    bot.cfg = MagicMock()
    bot.executor = MagicMock()
    bot.writer = MagicMock()
    bot.writer.active = False
    bot.transport = MagicMock()
    bot.transport.reply_text = MagicMock(return_value="mid")
    bot.store = MagicMock()
    bot.indexer = None
    bot._vector = None
    bot._thread_pool = MagicMock()
    return bot


def _make_event(text_or_content: str, msg_type: str = "text", sender_type: str = "user"):
    return SimpleNamespace(
        event=SimpleNamespace(
            message=SimpleNamespace(
                message_type=msg_type,
                message_id="msg123",
                chat_id="chat456",
                content=text_or_content if msg_type != "text" else json.dumps({"text": text_or_content}),
                mentions=None,
            ),
            sender=SimpleNamespace(sender_type=sender_type),
        )
    )


class TestImageMessageRouting:
    def test_image_message_triggers_download(self):
        bot = _make_bot()
        content = json.dumps({"image_key": "img_v2_test"})
        evt = _make_event(content, msg_type="image")

        fake_bytes = b"\xff\xd8\xff" + b"\x00" * 100
        bot.transport.download_image_message.return_value = fake_bytes

        with patch("lifebook.feishu.ingest_image") as mock_ingest:
            mock_ingest.return_value = MagicMock()
            bot._handle_message(evt)

        bot.transport.download_image_message.assert_called_once_with("msg123", "img_v2_test")

    def test_image_message_ingested(self):
        bot = _make_bot()
        content = json.dumps({"image_key": "img_v2_test"})
        evt = _make_event(content, msg_type="image")
        fake_bytes = b"\xff\xd8\xff" + b"\x00" * 100
        bot.transport.download_image_message.return_value = fake_bytes

        with patch("lifebook.feishu.ingest_image") as mock_ingest:
            mock_ingest.return_value = MagicMock()
            bot._handle_message(evt)

        mock_ingest.assert_called_once()
        call_kwargs = mock_ingest.call_args
        assert call_kwargs.kwargs.get("image_bytes") == fake_bytes or (
            len(call_kwargs.args) >= 2 and call_kwargs.args[1] == fake_bytes
        )

    def test_image_message_ack_reply(self):
        bot = _make_bot()
        content = json.dumps({"image_key": "img_v2_test"})
        evt = _make_event(content, msg_type="image")
        fake_bytes = b"\xff\xd8\xff" + b"\x00" * 100
        bot.transport.download_image_message.return_value = fake_bytes

        with patch("lifebook.feishu.ingest_image") as mock_ingest:
            mock_ingest.return_value = MagicMock()
            bot._handle_message(evt)

        reply_text = bot.transport.reply_text.call_args[0][1]
        assert "图片" in reply_text

    def test_image_download_failure_replies_error(self):
        bot = _make_bot()
        content = json.dumps({"image_key": "img_v2_test"})
        evt = _make_event(content, msg_type="image")
        bot.transport.download_image_message.return_value = None

        bot._handle_message(evt)

        reply_text = bot.transport.reply_text.call_args[0][1]
        assert "下载失败" in reply_text or "失败" in reply_text

    def test_image_missing_key_replies_error(self):
        bot = _make_bot()
        content = json.dumps({})
        evt = _make_event(content, msg_type="image")

        bot._handle_message(evt)

        reply_text = bot.transport.reply_text.call_args[0][1]
        assert "image_key" in reply_text or "缺少" in reply_text

    def test_image_ingest_failure_replies_error(self):
        bot = _make_bot()
        content = json.dumps({"image_key": "img_key"})
        evt = _make_event(content, msg_type="image")
        fake_bytes = b"\xff\xd8\xff" + b"\x00" * 100
        bot.transport.download_image_message.return_value = fake_bytes

        with patch("lifebook.feishu.ingest_image", side_effect=Exception("disk full")):
            bot._handle_message(evt)

        reply_text = bot.transport.reply_text.call_args[0][1]
        assert "失败" in reply_text

    def test_image_message_spawns_thread(self):
        bot = _make_bot()
        content = json.dumps({"image_key": "img_key"})
        evt = _make_event(content, msg_type="image")
        fake_bytes = b"\xff\xd8\xff" + b"\x00" * 100
        bot.transport.download_image_message.return_value = fake_bytes

        with patch("lifebook.feishu.ingest_image") as mock_ingest:
            mock_ingest.return_value = MagicMock()
            bot._handle_message(evt)

        bot._thread_pool.submit.assert_called_once()

    def test_other_non_text_still_rejected(self):
        bot = _make_bot()
        evt = _make_event("some content", msg_type="file")
        bot._handle_message(evt)
        reply_text = bot.transport.reply_text.call_args[0][1]
        assert "暂不支持" in reply_text
