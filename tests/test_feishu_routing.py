"""Unit tests for FeishuBot message routing logic."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


def _make_bot():
    """Create a FeishuBot with all external deps mocked, bypassing __init__."""
    from lifebook.feishu import FeishuBot
    bot = FeishuBot.__new__(FeishuBot)
    bot.cfg = MagicMock()
    bot.executor = MagicMock()
    bot.writer = MagicMock()
    bot.api = MagicMock()
    bot.store = MagicMock()
    bot.reply_text = MagicMock(return_value="mid")
    bot._ws_client = None
    return bot


def _make_event(text: str, msg_type="text", sender_type="user", mentions=None):
    """Build a fake P2ImMessageReceiveV1 data object."""
    return SimpleNamespace(
        event=SimpleNamespace(
            message=SimpleNamespace(
                message_type=msg_type,
                message_id="msg123",
                chat_id="chat456",
                content=json.dumps({"text": text}),
                mentions=mentions,
            ),
            sender=SimpleNamespace(sender_type=sender_type),
        )
    )


class TestWriteCommand:
    def test_write_with_idea_calls_writer_start(self):
        bot = _make_bot()
        bot.writer.start.return_value = "outline here"
        bot._run_write_cmd("msg123", "AI文章")
        bot.writer.start.assert_called_once_with("AI文章")
        bot.reply_text.assert_called_once_with("msg123", "outline here")

    def test_write_without_idea_replies_usage(self):
        bot = _make_bot()
        bot._handle_message(_make_event("/write"))
        bot.reply_text.assert_called_once()
        assert "请提供写作想法" in bot.reply_text.call_args[0][1]
        bot.writer.start.assert_not_called()

    def test_write_with_idea_routes_thread(self):
        bot = _make_bot()
        with patch("lifebook.feishu.threading") as mock_t:
            bot._handle_message(_make_event("/write 测试想法"))
            mock_t.Thread.assert_called_once()
            kw = mock_t.Thread.call_args[1]
            assert kw["target"] == bot._run_write_cmd
            assert kw["args"] == ("msg123", "测试想法")


class TestPublishCommand:
    def test_publish_calls_writer_publish(self):
        bot = _make_bot()
        bot.writer.publish.return_value = "published!"
        bot._run_publish_cmd("msg123")
        bot.writer.publish.assert_called_once()
        bot.reply_text.assert_called_once_with("msg123", "published!")

    def test_publish_routes_thread(self):
        bot = _make_bot()
        with patch("lifebook.feishu.threading") as mock_t:
            bot._handle_message(_make_event("/publish"))
            assert mock_t.Thread.call_args[1]["target"] == bot._run_publish_cmd


class TestWriterActiveRouting:
    def test_active_writer_routes_to_handle_message(self):
        bot = _make_bot()
        bot.writer.handle_message.return_value = "writer reply"
        bot._run_writer_msg("msg123", "hello")
        bot.writer.handle_message.assert_called_once_with("hello")
        bot.reply_text.assert_called_once_with("msg123", "writer reply")

    def test_active_writer_routing_in_handle_message(self):
        bot = _make_bot()
        bot.writer.active = True
        with patch("lifebook.feishu.threading") as mock_t:
            bot._handle_message(_make_event("some text"))
            assert mock_t.Thread.call_args[1]["target"] == bot._run_writer_msg

    def test_inactive_writer_routes_to_ingest(self):
        bot = _make_bot()
        bot.writer.active = False
        with patch("lifebook.feishu.ingest_text") as mock_ingest:
            mock_ingest.return_value = MagicMock()
            bot._handle_message(_make_event("just a note"))
            mock_ingest.assert_called_once()


class TestStatusCommand:
    def test_status_shows_writing_active(self):
        bot = _make_bot()
        bot.writer.active = True
        bot.writer.stage = "drafting"
        bot.executor.scan_inbox.return_value = []
        bot.cfg.knowledge.topics_path.exists.return_value = True
        bot.cfg.knowledge.topics_path.rglob.return_value = []
        # Call _reply_status directly since /status is intercepted by writer.active
        bot._reply_status("msg123")
        reply = bot.reply_text.call_args[0][1]
        assert "进行中" in reply
        assert "drafting" in reply

    def test_status_shows_writing_inactive(self):
        bot = _make_bot()
        bot.writer.active = False
        bot.executor.scan_inbox.return_value = []
        bot.cfg.knowledge.topics_path.exists.return_value = True
        bot.cfg.knowledge.topics_path.rglob.return_value = []
        bot._handle_message(_make_event("/status"))
        reply = bot.reply_text.call_args[0][1]
        assert "未启动" in reply


class TestEdgeCases:
    def test_bot_sender_ignored(self):
        bot = _make_bot()
        bot._handle_message(_make_event("hello", sender_type="bot"))
        bot.reply_text.assert_not_called()

    def test_non_text_message_rejected(self):
        bot = _make_bot()
        bot._handle_message(_make_event("hello", msg_type="image"))
        assert "暂不支持" in bot.reply_text.call_args[0][1]
