"""Tests for FeishuBot refactor: CommandRouter, MessageHandler, backpressure, reconnection."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, PropertyMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_event(text: str, msg_type="text", sender_type="user", mentions=None):
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


def _make_image_event(image_key="img_key_abc"):
    return SimpleNamespace(
        event=SimpleNamespace(
            message=SimpleNamespace(
                message_type="image",
                message_id="msg_img",
                chat_id="chat456",
                content=json.dumps({"image_key": image_key}),
                mentions=None,
            ),
            sender=SimpleNamespace(sender_type="user"),
        )
    )


def _make_transport():
    transport = MagicMock()
    transport.reply_text = MagicMock(return_value="mid")
    transport.download_image_message = MagicMock(return_value=b"\x89PNG\r\n")
    return transport


def _make_bot():
    from lifebook.feishu import FeishuBot
    from lifebook.feishu_commands import CommandRouter
    from lifebook.feishu_handler import MessageHandler
    bot = FeishuBot.__new__(FeishuBot)
    bot.cfg = MagicMock()
    bot.store = MagicMock()
    bot.executor = MagicMock()
    bot.writer = MagicMock()
    bot.transport = _make_transport()
    bot.indexer = None
    bot._vector = None
    bot._thread_pool = MagicMock()
    bot._in_flight: set[str] = set()
    bot._cmd_router = CommandRouter(
        transport=bot.transport,
        writer=bot.writer,
        executor=bot.executor,
        cfg=bot.cfg,
    )
    bot._msg_handler = MessageHandler(
        transport=bot.transport,
        cfg=bot.cfg,
        thread_pool=bot._thread_pool,
    )
    return bot


# ---------------------------------------------------------------------------
# CommandRouter tests
# ---------------------------------------------------------------------------

class TestCommandRouter:
    def test_dispatch_write_with_idea(self):
        from lifebook.feishu_commands import CommandRouter
        transport = _make_transport()
        writer = MagicMock()
        writer.start.return_value = "outline"
        router = CommandRouter(transport=transport, writer=writer, executor=MagicMock())
        router.dispatch_write("msg1", "AI article")
        writer.start.assert_called_once_with("AI article")
        transport.reply_text.assert_called_once_with("msg1", "outline")

    def test_dispatch_write_empty_idea(self):
        from lifebook.feishu_commands import CommandRouter
        transport = _make_transport()
        router = CommandRouter(transport=transport, writer=MagicMock(), executor=MagicMock())
        router.dispatch_write("msg1", "")
        transport.reply_text.assert_called_once()
        assert "请提供写作想法" in transport.reply_text.call_args[0][1]

    def test_dispatch_publish(self):
        from lifebook.feishu_commands import CommandRouter
        transport = _make_transport()
        writer = MagicMock()
        writer.publish.return_value = "done"
        router = CommandRouter(transport=transport, writer=writer, executor=MagicMock())
        router.dispatch_publish("msg1", force=True)
        writer.publish.assert_called_once_with(force=True)
        transport.reply_text.assert_called_once_with("msg1", "done")

    def test_dispatch_process_empty_inbox(self):
        from lifebook.feishu_commands import CommandRouter
        transport = _make_transport()
        executor = MagicMock()
        executor.process_inbox.return_value = []
        router = CommandRouter(transport=transport, writer=MagicMock(), executor=executor)
        router.dispatch_process("msg1")
        transport.reply_text.assert_called_once()
        assert "为空" in transport.reply_text.call_args[0][1]

    def test_dispatch_process_with_results(self):
        from lifebook.feishu_commands import CommandRouter
        from lifebook.executor import ProcessResult
        transport = _make_transport()
        executor = MagicMock()
        executor.process_inbox.return_value = [
            ProcessResult(Path("a"), True, topic_path=Path("/fake/t/a")),
        ]
        cfg = MagicMock()
        cfg.knowledge.root = Path("/fake")
        router = CommandRouter(transport=transport, writer=MagicMock(), executor=executor, cfg=cfg)
        router.dispatch_process("msg1")
        transport.reply_text.assert_called_once()

    def test_dispatch_update_index_not_initialized(self):
        from lifebook.feishu_commands import CommandRouter
        transport = _make_transport()
        router = CommandRouter(transport=transport, writer=MagicMock(), executor=MagicMock())
        router.dispatch_update_index("msg1", indexer=None)
        transport.reply_text.assert_called_once()
        assert "未初始化" in transport.reply_text.call_args[0][1]

    def test_dispatch_update_index_success(self):
        from lifebook.feishu_commands import CommandRouter
        transport = _make_transport()
        mock_indexer = MagicMock()
        mock_indexer.incremental_update.return_value = {
            "upserted": 3, "deleted": 1, "unchanged": 5, "errors": 0,
        }
        router = CommandRouter(transport=transport, writer=MagicMock(), executor=MagicMock())
        router.dispatch_update_index("msg1", indexer=mock_indexer)
        transport.reply_text.assert_called_once()
        reply = transport.reply_text.call_args[0][1]
        assert "向量索引更新完成" in reply

    def test_dispatch_search_no_results(self):
        from lifebook.feishu_commands import CommandRouter
        transport = _make_transport()
        vector = MagicMock()
        vector.search.return_value = []
        router = CommandRouter(transport=transport, writer=MagicMock(), executor=MagicMock())
        router.dispatch_search("msg1", "query", vector=vector)
        transport.reply_text.assert_called_once()
        assert "未找到" in transport.reply_text.call_args[0][1]

    def test_dispatch_search_with_results(self):
        from lifebook.feishu_commands import CommandRouter
        transport = _make_transport()
        vector = MagicMock()
        vector.search.return_value = [
            SimpleNamespace(doc_id="doc1", distance=0.2, metadata={"title": "Test"}, text="short"),
        ]
        router = CommandRouter(transport=transport, writer=MagicMock(), executor=MagicMock())
        router.dispatch_search("msg1", "query", vector=vector)
        transport.reply_text.assert_called_once()
        assert "Test" in transport.reply_text.call_args[0][1]

    def test_dispatch_search_empty_query(self):
        from lifebook.feishu_commands import CommandRouter
        transport = _make_transport()
        router = CommandRouter(transport=transport, writer=MagicMock(), executor=MagicMock())
        router.dispatch_search("msg1", "")
        transport.reply_text.assert_called_once()
        assert "请提供搜索词" in transport.reply_text.call_args[0][1]

    def test_dispatch_restore(self):
        from lifebook.feishu_commands import CommandRouter
        transport = _make_transport()
        writer = MagicMock()
        writer.restore_draft.return_value = "restored"
        router = CommandRouter(transport=transport, writer=writer, executor=MagicMock())
        router.dispatch_restore("msg1")
        writer.restore_draft.assert_called_once()
        transport.reply_text.assert_called_once_with("msg1", "restored")

    def test_dispatch_writer_message(self):
        from lifebook.feishu_commands import CommandRouter
        transport = _make_transport()
        writer = MagicMock()
        writer.handle_message.return_value = "reply"
        router = CommandRouter(transport=transport, writer=writer, executor=MagicMock())
        router.dispatch_writer_message("msg1", "hello")
        writer.handle_message.assert_called_once_with("hello")
        transport.reply_text.assert_called_once_with("msg1", "reply")


# ---------------------------------------------------------------------------
# MessageHandler tests
# ---------------------------------------------------------------------------

class TestMessageHandler:
    def test_handle_image_ingests(self):
        from lifebook.feishu_handler import MessageHandler
        transport = _make_transport()
        cfg = MagicMock()
        handler = MessageHandler(transport=transport, cfg=cfg, thread_pool=MagicMock())
        with patch("lifebook.feishu_handler.ingest_image") as mock_ingest:
            mock_ingest.return_value = MagicMock()
            with patch("lifebook.feishu_handler.detect_mime_type", return_value="image/png"):
                handler.handle_image_message("msg1", json.dumps({"image_key": "img1"}))
        mock_ingest.assert_called_once()
        assert "已收到图片" in transport.reply_text.call_args[0][1]

    def test_handle_image_no_key(self):
        from lifebook.feishu_handler import MessageHandler
        transport = _make_transport()
        handler = MessageHandler(transport=transport, cfg=MagicMock(), thread_pool=MagicMock())
        handler.handle_image_message("msg1", "{}")
        assert "缺少 image_key" in transport.reply_text.call_args[0][1]

    def test_handle_image_download_fails(self):
        from lifebook.feishu_handler import MessageHandler
        transport = _make_transport()
        transport.download_image_message.return_value = None
        handler = MessageHandler(transport=transport, cfg=MagicMock(), thread_pool=MagicMock())
        handler.handle_image_message("msg1", json.dumps({"image_key": "img1"}))
        assert "下载失败" in transport.reply_text.call_args[0][1]

    def test_handle_url_message(self):
        from lifebook.feishu_handler import MessageHandler
        transport = _make_transport()
        cfg = MagicMock()
        tp = MagicMock()
        handler = MessageHandler(transport=transport, cfg=cfg, thread_pool=tp)
        with patch("lifebook.feishu_handler.ingest_url") as mock_ingest:
            mock_ingest.return_value = Path("/fake/inbox.md")
            handler.handle_url_message("msg1", "check https://example.com", ["https://example.com"])
        mock_ingest.assert_called_once()
        assert "已收到链接" in transport.reply_text.call_args[0][1]
        tp.submit.assert_called_once()

    def test_handle_url_message_error(self):
        from lifebook.feishu_handler import MessageHandler
        transport = _make_transport()
        cfg = MagicMock()
        handler = MessageHandler(transport=transport, cfg=cfg, thread_pool=MagicMock())
        with patch("lifebook.feishu_handler.ingest_url", side_effect=Exception("fail")):
            handler.handle_url_message("msg1", "check https://example.com", ["https://example.com"])
        assert "录入失败" in transport.reply_text.call_args[0][1]

    def test_handle_text_message(self):
        from lifebook.feishu_handler import MessageHandler
        transport = _make_transport()
        cfg = MagicMock()
        tp = MagicMock()
        handler = MessageHandler(transport=transport, cfg=cfg, thread_pool=tp)
        with patch("lifebook.feishu_handler.ingest_text") as mock_ingest:
            mock_ingest.return_value = Path("/fake/note.md")
            handler.handle_text_message("msg1", "just a note")
        mock_ingest.assert_called_once()
        assert "已收到笔记" in transport.reply_text.call_args[0][1]
        tp.submit.assert_called_once()

    def test_handle_text_message_error(self):
        from lifebook.feishu_handler import MessageHandler
        transport = _make_transport()
        cfg = MagicMock()
        handler = MessageHandler(transport=transport, cfg=cfg, thread_pool=MagicMock())
        with patch("lifebook.feishu_handler.ingest_text", side_effect=Exception("fail")):
            handler.handle_text_message("msg1", "just a note")
        assert "录入失败" in transport.reply_text.call_args[0][1]


# ---------------------------------------------------------------------------
# WebSocket reconnection tests
# ---------------------------------------------------------------------------

class TestWebSocketReconnection:
    def test_start_with_reconnect_creates_client(self):
        """Verify start_with_reconnect creates a lark.ws.Client and calls start()."""
        from lifebook.feishu_transport import FeishuTransport
        cfg = MagicMock()
        cfg.app_id = "app"
        cfg.app_secret = "secret"
        transport = FeishuTransport.__new__(FeishuTransport)
        transport.cfg = cfg
        transport._ws_client = None

        with patch("lifebook.feishu_transport.lark") as mock_lark:
            mock_ws = MagicMock()
            mock_lark.ws.Client.return_value = mock_ws
            mock_lark.LogLevel.WARNING = 0

            # Make start() succeed then raise KeyboardInterrupt to exit loop
            mock_ws.start.side_effect = [None, KeyboardInterrupt()]

            with patch("lifebook.feishu_transport.time.sleep"):
                transport.start_with_reconnect(MagicMock())

        mock_lark.ws.Client.assert_called()
        assert mock_ws.start.call_count == 2

    def test_reconnects_after_exception(self):
        """Verify reconnection happens when start() raises an exception."""
        from lifebook.feishu_transport import FeishuTransport, _INITIAL_BACKOFF
        cfg = MagicMock()
        cfg.app_id = "app"
        cfg.app_secret = "secret"
        transport = FeishuTransport.__new__(FeishuTransport)
        transport.cfg = cfg
        transport._ws_client = None

        call_count = 0

        def fake_start():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("ws closed")
            raise KeyboardInterrupt()

        with patch("lifebook.feishu_transport.lark") as mock_lark:
            mock_ws = MagicMock()
            mock_lark.ws.Client.return_value = mock_ws
            mock_ws.start.side_effect = fake_start
            mock_lark.LogLevel.WARNING = 0

            sleep_calls = []
            with patch("lifebook.feishu_transport.time.sleep", side_effect=lambda s: sleep_calls.append(s)):
                transport.start_with_reconnect(MagicMock())

        assert call_count == 3
        assert len(sleep_calls) == 2
        assert sleep_calls[0] == _INITIAL_BACKOFF
        assert sleep_calls[1] == _INITIAL_BACKOFF * 2

    def test_backoff_caps_at_60(self):
        """Verify backoff never exceeds _MAX_BACKOFF."""
        from lifebook.feishu_transport import FeishuTransport, _MAX_BACKOFF
        cfg = MagicMock()
        cfg.app_id = "app"
        cfg.app_secret = "secret"
        transport = FeishuTransport.__new__(FeishuTransport)
        transport.cfg = cfg
        transport._ws_client = None

        call_count = 0

        def fake_start():
            nonlocal call_count
            call_count += 1
            if call_count >= 7:
                raise KeyboardInterrupt()
            raise ConnectionError("always fail")

        with patch("lifebook.feishu_transport.lark") as mock_lark:
            mock_ws = MagicMock()
            mock_lark.ws.Client.return_value = mock_ws
            mock_ws.start.side_effect = fake_start
            mock_lark.LogLevel.WARNING = 0

            sleep_calls = []
            with patch("lifebook.feishu_transport.time.sleep", side_effect=lambda s: sleep_calls.append(s)):
                transport.start_with_reconnect(MagicMock())

        # 6 failures before KeyboardInterrupt, so 6 sleep calls
        assert len(sleep_calls) == 6
        assert all(s <= _MAX_BACKOFF for s in sleep_calls)
        # Backoff: 1, 2, 4, 8, 16, 32 (all under 60)
        assert sleep_calls == [1, 2, 4, 8, 16, 32]


# ---------------------------------------------------------------------------
# Backpressure tests
# ---------------------------------------------------------------------------

class TestBackpressure:
    def test_rejects_overlapping_process(self):
        bot = _make_bot()
        bot._in_flight = {"process"}
        bot._handle_message(_make_event("/process"))
        # Should be rejected, not submitted to thread pool
        bot.transport.reply_text.assert_called_once()
        assert "正在执行" in bot.transport.reply_text.call_args[0][1] or "busy" in bot.transport.reply_text.call_args[0][1].lower()

    def test_rejects_overlapping_update_index(self):
        bot = _make_bot()
        bot._in_flight = {"update-index"}
        bot._handle_message(_make_event("/update-index"))
        bot.transport.reply_text.assert_called_once()

    def test_allows_different_commands(self):
        bot = _make_bot()
        bot._in_flight = {"process"}
        bot._handle_message(_make_event("/write 我的想法"))
        bot._thread_pool.submit.assert_called_once()

    def test_allows_same_command_when_not_busy(self):
        bot = _make_bot()
        bot._in_flight = set()
        bot._handle_message(_make_event("/process"))
        bot._thread_pool.submit.assert_called_once()


# ---------------------------------------------------------------------------
# Error message leakage tests
# ---------------------------------------------------------------------------

class TestErrorLeakage:
    def test_dispatch_write_hides_exception(self):
        from lifebook.feishu_commands import CommandRouter
        transport = _make_transport()
        writer = MagicMock()
        writer.start.side_effect = Exception("secret API key leaked: sk-abc123")
        router = CommandRouter(transport=transport, writer=writer, executor=MagicMock())
        router.dispatch_write("msg1", "idea")
        reply = transport.reply_text.call_args[0][1]
        assert "sk-abc123" not in reply
        assert "操作失败" in reply

    def test_dispatch_publish_hides_exception(self):
        from lifebook.feishu_commands import CommandRouter
        transport = _make_transport()
        writer = MagicMock()
        writer.publish.side_effect = RuntimeError("internal db password: xyz")
        router = CommandRouter(transport=transport, writer=writer, executor=MagicMock())
        router.dispatch_publish("msg1")
        reply = transport.reply_text.call_args[0][1]
        assert "xyz" not in reply
        assert "操作失败" in reply

    def test_dispatch_writer_message_hides_exception(self):
        from lifebook.feishu_commands import CommandRouter
        transport = _make_transport()
        writer = MagicMock()
        writer.handle_message.side_effect = ValueError("token expired: tok_999")
        router = CommandRouter(transport=transport, writer=writer, executor=MagicMock())
        router.dispatch_writer_message("msg1", "text")
        reply = transport.reply_text.call_args[0][1]
        assert "tok_999" not in reply
        assert "操作失败" in reply

    def test_dispatch_restore_hides_exception(self):
        from lifebook.feishu_commands import CommandRouter
        transport = _make_transport()
        writer = MagicMock()
        writer.restore_draft.side_effect = OSError("permission denied /secret/path")
        router = CommandRouter(transport=transport, writer=writer, executor=MagicMock())
        router.dispatch_restore("msg1")
        reply = transport.reply_text.call_args[0][1]
        assert "/secret/path" not in reply
        assert "操作失败" in reply

    def test_dispatch_update_index_hides_exception(self):
        from lifebook.feishu_commands import CommandRouter
        transport = _make_transport()
        mock_indexer = MagicMock()
        mock_indexer.incremental_update.side_effect = RuntimeError("db connection refused at 10.0.0.5:5432")
        router = CommandRouter(transport=transport, writer=MagicMock(), executor=MagicMock())
        router.dispatch_update_index("msg1", indexer=mock_indexer)
        reply = transport.reply_text.call_args[0][1]
        assert "10.0.0.5" not in reply
        assert "操作失败" in reply

    def test_dispatch_search_hides_exception(self):
        from lifebook.feishu_commands import CommandRouter
        transport = _make_transport()
        mock_vi = MagicMock()
        mock_vi.search.side_effect = RuntimeError("chromadb auth token expired")
        router = CommandRouter(transport=transport, writer=MagicMock(), executor=MagicMock())
        router.dispatch_search("msg1", "query", vector=mock_vi)
        reply = transport.reply_text.call_args[0][1]
        assert "auth token" not in reply
        assert "操作失败" in reply

    def test_ingest_image_error_hides_exception(self):
        from lifebook.feishu_handler import MessageHandler
        transport = _make_transport()
        cfg = MagicMock()
        handler = MessageHandler(transport=transport, cfg=cfg, thread_pool=MagicMock())
        with patch("lifebook.feishu_handler.detect_mime_type", return_value="image/png"):
            with patch("lifebook.feishu_handler.ingest_image", side_effect=RuntimeError("API key invalid: sk-xyz")):
                handler.handle_image_message("msg1", json.dumps({"image_key": "img1"}))
        reply = transport.reply_text.call_args[0][1]
        assert "sk-xyz" not in reply
        assert "图片录入失败" in reply
