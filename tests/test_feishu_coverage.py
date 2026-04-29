"""Coverage tests for feishu.py missing lines."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


def _make_bot():
    from lifebook.feishu import FeishuBot
    from lifebook.feishu_commands import CommandRouter
    from lifebook.feishu_handler import MessageHandler
    bot = FeishuBot.__new__(FeishuBot)
    bot.cfg = MagicMock()
    bot.store = MagicMock()
    bot.executor = MagicMock()
    bot.writer = MagicMock()
    bot.transport = MagicMock()
    bot.transport.reply_text = MagicMock(return_value="mid")
    bot.indexer = None
    bot._vector = None
    bot._thread_pool = MagicMock()
    bot._in_flight = set()
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


class TestExtractText:
    def test_valid_json_text(self):
        from lifebook.feishu import _extract_text
        assert _extract_text('{"text": "hello"}') == "hello"

    def test_valid_json_content(self):
        from lifebook.feishu import _extract_text
        assert _extract_text('{"content": "world"}') == "world"

    def test_invalid_json(self):
        from lifebook.feishu import _extract_text
        assert _extract_text("not json") == "not json"

    def test_non_dict_json(self):
        from lifebook.feishu import _extract_text
        assert _extract_text("[1, 2]") == "[1, 2]"

    def test_empty_dict(self):
        from lifebook.feishu import _extract_text
        assert _extract_text("{}") == ""


class TestStripMentions:
    def test_no_mentions(self):
        from lifebook.feishu import _strip_mentions
        assert _strip_mentions("hello", None) == "hello"

    def test_strips_mention_key(self):
        from lifebook.feishu import _strip_mentions
        m = SimpleNamespace(key="@bot")
        assert _strip_mentions("@bot hello", [m]) == "hello"

    def test_dict_mention(self):
        from lifebook.feishu import _strip_mentions
        assert _strip_mentions("@bot hello", [{"key": "@bot"}]) == "hello"


class TestSendReplyText:
    def test_send_text_success(self):
        from lifebook.feishu_transport import FeishuTransport
        cfg = MagicMock()
        cfg.app_id = "app"
        cfg.app_secret = "secret"
        with patch("lifebook.feishu_transport.lark.Client") as MockClient:
            transport = FeishuTransport(cfg)
            mock_resp = MagicMock()
            mock_resp.success.return_value = True
            mock_resp.data.message_id = "mid123"
            transport.api.im.v1.message.create.return_value = mock_resp
            with patch("lifebook.feishu_transport.CreateMessageRequestBody") as MockBody:
                with patch("lifebook.feishu_transport.CreateMessageRequest") as MockReq:
                    MockBody.builder.return_value.receive_id.return_value.msg_type.return_value.content.return_value.build.return_value = MagicMock()
                    MockReq.builder.return_value.receive_id_type.return_value.request_body.return_value.build.return_value = MagicMock()
                    result = transport.send_text("chat1", "hello")
        assert result == "mid123"


class TestSendFile:
    def test_send_file_success(self):
        from lifebook.feishu_transport import FeishuTransport
        cfg = MagicMock()
        cfg.app_id = "app"
        cfg.app_secret = "secret"
        with patch("lifebook.feishu_transport.lark.Client"):
            transport = FeishuTransport(cfg)
            mock_resp = MagicMock()
            mock_resp.success.return_value = True
            mock_resp.data.message_id = "file_msg_123"
            transport.api.im.v1.message.create.return_value = mock_resp
            with patch("lifebook.feishu_transport.CreateMessageRequestBody") as MockBody:
                with patch("lifebook.feishu_transport.CreateMessageRequest") as MockReq:
                    MockBody.builder.return_value.receive_id.return_value.msg_type.return_value.content.return_value.build.return_value = MagicMock()
                    MockReq.builder.return_value.receive_id_type.return_value.request_body.return_value.build.return_value = MagicMock()
                    result = transport.send_file("chat1", "file_key_abc")
        assert result == "file_msg_123"

    def test_send_file_failure(self):
        from lifebook.feishu_transport import FeishuTransport
        cfg = MagicMock()
        cfg.app_id = "app"
        cfg.app_secret = "secret"
        with patch("lifebook.feishu_transport.lark.Client"):
            transport = FeishuTransport(cfg)
            mock_resp = MagicMock()
            mock_resp.success.return_value = False
            mock_resp.code = 500
            mock_resp.msg = "error"
            transport.api.im.v1.message.create.return_value = mock_resp
            with patch("lifebook.feishu_transport.CreateMessageRequestBody") as MockBody:
                with patch("lifebook.feishu_transport.CreateMessageRequest") as MockReq:
                    MockBody.builder.return_value.receive_id.return_value.msg_type.return_value.content.return_value.build.return_value = MagicMock()
                    MockReq.builder.return_value.receive_id_type.return_value.request_body.return_value.build.return_value = MagicMock()
                    result = transport.send_file("chat1", "file_key_abc")
        assert result is None


class TestDownloadImage:
    def test_download_success(self):
        from lifebook.feishu_transport import FeishuTransport
        cfg = MagicMock()
        cfg.app_id = "app"
        cfg.app_secret = "secret"
        with patch("lifebook.feishu_transport.lark.Client"):
            transport = FeishuTransport(cfg)
            mock_resp = MagicMock()
            mock_resp.success.return_value = True
            mock_resp.file.read.return_value = b"\x89PNG\r\n"
            transport.api.im.v1.message_resource.get.return_value = mock_resp
            result = transport.download_image_message("msg1", "img_key_1")
        assert result == b"\x89PNG\r\n"

    def test_download_api_failure(self):
        from lifebook.feishu_transport import FeishuTransport
        cfg = MagicMock()
        cfg.app_id = "app"
        cfg.app_secret = "secret"
        with patch("lifebook.feishu_transport.lark.Client"):
            transport = FeishuTransport(cfg)
            mock_resp = MagicMock()
            mock_resp.success.return_value = False
            mock_resp.code = 404
            mock_resp.msg = "not found"
            transport.api.im.v1.message_resource.get.return_value = mock_resp
            result = transport.download_image_message("msg1", "img_key_1")
        assert result is None

    def test_download_no_file_in_response(self):
        from lifebook.feishu_transport import FeishuTransport
        cfg = MagicMock()
        cfg.app_id = "app"
        cfg.app_secret = "secret"
        with patch("lifebook.feishu_transport.lark.Client"):
            transport = FeishuTransport(cfg)
            mock_resp = MagicMock()
            mock_resp.success.return_value = True
            mock_resp.file = None
            transport.api.im.v1.message_resource.get.return_value = mock_resp
            result = transport.download_image_message("msg1", "img_key_1")
        assert result is None

    def test_send_text_failure(self):
        from lifebook.feishu_transport import FeishuTransport
        cfg = MagicMock()
        cfg.app_id = "app"
        cfg.app_secret = "secret"
        with patch("lifebook.feishu_transport.lark.Client") as MockClient:
            transport = FeishuTransport(cfg)
            mock_resp = MagicMock()
            mock_resp.success.return_value = False
            mock_resp.code = 500
            mock_resp.msg = "error"
            transport.api.im.v1.message.create.return_value = mock_resp
            with patch("lifebook.feishu_transport.CreateMessageRequestBody") as MockBody:
                with patch("lifebook.feishu_transport.CreateMessageRequest") as MockReq:
                    MockBody.builder.return_value.receive_id.return_value.msg_type.return_value.content.return_value.build.return_value = MagicMock()
                    MockReq.builder.return_value.receive_id_type.return_value.request_body.return_value.build.return_value = MagicMock()
                    result = transport.send_text("chat1", "hello")
        assert result is None

    def test_reply_text_success(self):
        from lifebook.feishu_transport import FeishuTransport
        cfg = MagicMock()
        cfg.app_id = "app"
        cfg.app_secret = "secret"
        with patch("lifebook.feishu_transport.lark.Client") as MockClient:
            transport = FeishuTransport(cfg)
            mock_resp = MagicMock()
            mock_resp.success.return_value = True
            mock_resp.data.message_id = "reply123"
            transport.api.im.v1.message.reply.return_value = mock_resp
            with patch("lifebook.feishu_transport.ReplyMessageRequestBody") as MockBody:
                with patch("lifebook.feishu_transport.ReplyMessageRequest") as MockReq:
                    MockBody.builder.return_value.msg_type.return_value.content.return_value.build.return_value = MagicMock()
                    MockReq.builder.return_value.message_id.return_value.request_body.return_value.build.return_value = MagicMock()
                    result = transport.reply_text("msg1", "hello")
        assert result == "reply123"

    def test_reply_text_failure(self):
        from lifebook.feishu_transport import FeishuTransport
        cfg = MagicMock()
        cfg.app_id = "app"
        cfg.app_secret = "secret"
        with patch("lifebook.feishu_transport.lark.Client") as MockClient:
            transport = FeishuTransport(cfg)
            mock_resp = MagicMock()
            mock_resp.success.return_value = False
            mock_resp.code = 500
            mock_resp.msg = "error"
            transport.api.im.v1.message.reply.return_value = mock_resp
            with patch("lifebook.feishu_transport.ReplyMessageRequestBody") as MockBody:
                with patch("lifebook.feishu_transport.ReplyMessageRequest") as MockReq:
                    MockBody.builder.return_value.msg_type.return_value.content.return_value.build.return_value = MagicMock()
                    MockReq.builder.return_value.message_id.return_value.request_body.return_value.build.return_value = MagicMock()
                    result = transport.reply_text("msg1", "hello")
        assert result is None

    def test_empty_text_after_strip(self):
        bot = _make_bot()
        evt = _make_event("@bot")
        evt.event.message.mentions = [SimpleNamespace(key="@bot")]
        bot._handle_message(evt)
        # Should not reply since text is empty after stripping mention
        bot.transport.reply_text.assert_not_called()


class TestNonTextMessage:
    def test_replies_for_non_text(self):
        bot = _make_bot()
        evt = _make_event("doc", msg_type="file")
        bot._handle_message(evt)
        bot.transport.reply_text.assert_called_once()
        assert "暂不支持" in bot.transport.reply_text.call_args[0][1]


class TestSlashCommands:
    def test_write_empty_shows_hint(self):
        bot = _make_bot()
        bot._handle_message(_make_event("/write"))
        bot.transport.reply_text.assert_called_once()
        assert "请提供写作想法" in bot.transport.reply_text.call_args[0][1]

    def test_write_with_idea_starts_thread(self):
        bot = _make_bot()
        bot._handle_message(_make_event("/write my idea"))
        bot._thread_pool.submit.assert_called_once()

    def test_publish_starts_thread(self):
        bot = _make_bot()
        bot._handle_message(_make_event("/publish"))
        bot._thread_pool.submit.assert_called_once()

    def test_publish_force(self):
        bot = _make_bot()
        bot._handle_message(_make_event("/publish!"))
        bot._thread_pool.submit.assert_called_once()

    def test_restore_starts_thread(self):
        bot = _make_bot()
        bot._handle_message(_make_event("/restore"))
        bot._thread_pool.submit.assert_called_once()

    def test_process_starts_thread(self):
        bot = _make_bot()
        bot._handle_message(_make_event("/process"))
        bot._thread_pool.submit.assert_called_once()

    def test_update_index_starts_thread(self):
        bot = _make_bot()
        bot._handle_message(_make_event("/update-index"))
        bot._thread_pool.submit.assert_called_once()

    def test_search_empty_shows_hint(self):
        bot = _make_bot()
        bot._handle_message(_make_event("/search"))
        bot.transport.reply_text.assert_called_once()
        assert "请提供搜索词" in bot.transport.reply_text.call_args[0][1]

    def test_search_with_query_starts_thread(self):
        bot = _make_bot()
        bot._handle_message(_make_event("/search test query"))
        bot._thread_pool.submit.assert_called_once()


class TestUrlAndTextMessages:
    def test_url_message_ingests_and_processes(self):
        bot = _make_bot()
        bot.writer.active = False
        with patch("lifebook.feishu_handler.ingest_url") as mock_ingest:
            mock_ingest.return_value = Path("/fake/test.md")
            bot._handle_message(_make_event("check https://example.com"))
        mock_ingest.assert_called_once()

    def test_url_message_ingest_error(self):
        bot = _make_bot()
        bot.writer.active = False
        with patch("lifebook.feishu_handler.ingest_url", side_effect=Exception("fail")):
            bot._handle_message(_make_event("check https://example.com"))
        bot.transport.reply_text.assert_called()
        assert "录入失败" in str(bot.transport.reply_text.call_args)

    def test_multiple_urls(self):
        bot = _make_bot()
        bot.writer.active = False
        with patch("lifebook.feishu_handler.ingest_url") as mock_ingest:
            mock_ingest.return_value = Path("/fake/test.md")
            bot._handle_message(_make_event("https://a.com https://b.com"))
        assert mock_ingest.call_count == 2

    def test_text_message_ingests(self):
        bot = _make_bot()
        bot.writer.active = False
        with patch("lifebook.feishu_handler.ingest_text") as mock_ingest:
            mock_ingest.return_value = Path("/fake/test.md")
            bot._handle_message(_make_event("just a note"))
        mock_ingest.assert_called_once()

    def test_text_message_ingest_error(self):
        bot = _make_bot()
        bot.writer.active = False
        with patch("lifebook.feishu_handler.ingest_text", side_effect=Exception("fail")):
            bot._handle_message(_make_event("just a note"))
        bot.transport.reply_text.assert_called()
        assert "录入失败" in str(bot.transport.reply_text.call_args)

    def test_writing_mode_routes_to_writer(self):
        bot = _make_bot()
        bot.writer.active = True
        bot._handle_message(_make_event("feedback text"))
        bot._thread_pool.submit.assert_called_once()


class TestProcessAndReply:
    def test_process_and_reply_ok(self):
        from lifebook.feishu_handler import MessageHandler
        from lifebook.executor import ProcessResult
        transport = MagicMock()
        transport.reply_text = MagicMock(return_value="mid")
        cfg = MagicMock()
        tp = MagicMock()
        handler = MessageHandler(transport=transport, cfg=cfg, thread_pool=tp)

        with patch("lifebook.executor.Executor") as MockExec:
            mock_exec = MockExec.return_value
            mock_exec.process_file.return_value = ProcessResult(
                Path("/fake/test.md"), True, topic_path=Path("/fake/topics/test.md"),
            )
            cfg.knowledge.root = Path("/fake")
            handler._process_and_reply("msg123", [Path("/fake/test.md")])
        transport.reply_text.assert_called()

    def test_process_and_reply_exception(self):
        from lifebook.feishu_handler import MessageHandler
        transport = MagicMock()
        transport.reply_text = MagicMock(return_value="mid")
        cfg = MagicMock()
        tp = MagicMock()
        handler = MessageHandler(transport=transport, cfg=cfg, thread_pool=tp)

        with patch("lifebook.executor.Executor") as MockExec:
            mock_exec = MockExec.return_value
            mock_exec.process_file.side_effect = Exception("crash")
            handler._process_and_reply("msg123", [Path("/fake/test.md")])
        transport.reply_text.assert_called()
        assert "失败" in transport.reply_text.call_args[0][1]


class TestFormatResults:
    def test_empty_results(self):
        from lifebook.feishu_commands import CommandRouter
        transport = MagicMock()
        router = CommandRouter(transport=transport, writer=MagicMock(), executor=MagicMock())
        result = router._format_results([])
        assert "没有结果" in result

    def test_show_summary(self):
        from lifebook.feishu_commands import CommandRouter
        from lifebook.executor import ProcessResult
        transport = MagicMock()
        cfg = MagicMock()
        cfg.knowledge.root = Path("/fake")
        router = CommandRouter(transport=transport, writer=MagicMock(), executor=MagicMock(), cfg=cfg)
        results = [
            ProcessResult(Path("a"), True, topic_path=Path("/fake/t/a")),
            ProcessResult(Path("b"), False, skipped_reason="dup"),
            ProcessResult(Path("c"), False, error="fail"),
        ]
        result = router._format_results(results, show_summary=True)
        assert "成功" in result
        assert "跳过" in result
        assert "失败" in result


class TestRunCommands:
    def test_dispatch_write_exception(self):
        from lifebook.feishu_commands import CommandRouter
        transport = MagicMock()
        transport.reply_text = MagicMock(return_value="mid")
        writer = MagicMock()
        writer.start.side_effect = Exception("crash")
        router = CommandRouter(transport=transport, writer=writer, executor=MagicMock())
        router.dispatch_write("msg123", "idea")
        transport.reply_text.assert_called()
        assert "操作失败" in transport.reply_text.call_args[0][1]

    def test_dispatch_publish_exception(self):
        from lifebook.feishu_commands import CommandRouter
        transport = MagicMock()
        transport.reply_text = MagicMock(return_value="mid")
        writer = MagicMock()
        writer.publish.side_effect = Exception("crash")
        router = CommandRouter(transport=transport, writer=writer, executor=MagicMock())
        router.dispatch_publish("msg123")
        transport.reply_text.assert_called()
        assert "操作失败" in transport.reply_text.call_args[0][1]

    def test_dispatch_writer_message_exception(self):
        from lifebook.feishu_commands import CommandRouter
        transport = MagicMock()
        transport.reply_text = MagicMock(return_value="mid")
        writer = MagicMock()
        writer.handle_message.side_effect = Exception("crash")
        router = CommandRouter(transport=transport, writer=writer, executor=MagicMock())
        router.dispatch_writer_message("msg123", "text")
        transport.reply_text.assert_called()
        assert "操作失败" in transport.reply_text.call_args[0][1]

    def test_dispatch_restore_exception(self):
        from lifebook.feishu_commands import CommandRouter
        transport = MagicMock()
        transport.reply_text = MagicMock(return_value="mid")
        writer = MagicMock()
        writer.restore_draft.side_effect = Exception("crash")
        router = CommandRouter(transport=transport, writer=writer, executor=MagicMock())
        router.dispatch_restore("msg123")
        transport.reply_text.assert_called()
        assert "操作失败" in transport.reply_text.call_args[0][1]

    def test_dispatch_process_empty(self):
        from lifebook.feishu_commands import CommandRouter
        transport = MagicMock()
        transport.reply_text = MagicMock(return_value="mid")
        executor = MagicMock()
        executor.process_inbox.return_value = []
        router = CommandRouter(transport=transport, writer=MagicMock(), executor=executor)
        router.dispatch_process("msg123")
        transport.reply_text.assert_called()
        assert "为空" in transport.reply_text.call_args[0][1]

    def test_dispatch_process_with_results(self):
        from lifebook.feishu_commands import CommandRouter
        from lifebook.executor import ProcessResult
        transport = MagicMock()
        transport.reply_text = MagicMock(return_value="mid")
        executor = MagicMock()
        executor.process_inbox.return_value = [
            ProcessResult(Path("a"), True, topic_path=Path("/fake/t/a")),
        ]
        cfg = MagicMock()
        cfg.knowledge.root = Path("/fake")
        router = CommandRouter(transport=transport, writer=MagicMock(), executor=executor, cfg=cfg)
        router.dispatch_process("msg123")
        transport.reply_text.assert_called()

    def test_dispatch_update_index_success(self):
        from lifebook.feishu_commands import CommandRouter
        transport = MagicMock()
        transport.reply_text = MagicMock(return_value="mid")
        mock_indexer_inst = MagicMock()
        mock_indexer_inst.incremental_update.return_value = {
            "upserted": 3, "deleted": 1, "unchanged": 5,
            "errors": 4,
        }
        router = CommandRouter(transport=transport, writer=MagicMock(), executor=MagicMock())
        router.dispatch_update_index("msg123", indexer=mock_indexer_inst)
        transport.reply_text.assert_called()
        reply = transport.reply_text.call_args[0][1]
        assert "向量索引更新完成" in reply

    def test_dispatch_update_index_not_initialized(self):
        from lifebook.feishu_commands import CommandRouter
        transport = MagicMock()
        transport.reply_text = MagicMock(return_value="mid")
        router = CommandRouter(transport=transport, writer=MagicMock(), executor=MagicMock())
        router.dispatch_update_index("msg123", indexer=None)
        transport.reply_text.assert_called()
        assert "未初始化" in transport.reply_text.call_args[0][1]

    def test_dispatch_search_no_results(self):
        from lifebook.feishu_commands import CommandRouter
        transport = MagicMock()
        transport.reply_text = MagicMock(return_value="mid")
        mock_vi = MagicMock()
        mock_vi.search.return_value = []
        router = CommandRouter(transport=transport, writer=MagicMock(), executor=MagicMock())
        router.dispatch_search("msg123", "query", vector=mock_vi)
        transport.reply_text.assert_called()
        assert "未找到" in transport.reply_text.call_args[0][1]

    def test_dispatch_search_with_results(self):
        from lifebook.feishu_commands import CommandRouter
        transport = MagicMock()
        transport.reply_text = MagicMock(return_value="mid")
        mock_vi = MagicMock()
        mock_vi.search.return_value = [
            SimpleNamespace(doc_id="doc1", distance=0.2, metadata={"title": "Test"}, text="x" * 150),
        ]
        router = CommandRouter(transport=transport, writer=MagicMock(), executor=MagicMock())
        router.dispatch_search("msg123", "query", vector=mock_vi)
        transport.reply_text.assert_called()
        reply = transport.reply_text.call_args[0][1]
        assert "Test" in reply

    def test_dispatch_search_exception(self):
        from lifebook.feishu_commands import CommandRouter
        transport = MagicMock()
        transport.reply_text = MagicMock(return_value="mid")
        mock_vi = MagicMock()
        mock_vi.search.side_effect = Exception("fail")
        router = CommandRouter(transport=transport, writer=MagicMock(), executor=MagicMock())
        router.dispatch_search("msg123", "query", vector=mock_vi)
        transport.reply_text.assert_called()
        assert "操作失败" in transport.reply_text.call_args[0][1]


class TestLifecycle:
    def test_start_delegates_to_transport(self):
        bot = _make_bot()
        mock_indexer_inst = MagicMock()
        mock_indexer_inst.start = MagicMock()
        mock_vi = MagicMock()
        with patch("lifebook.feishu.FeishuBot.start", wraps=bot.start):
            with patch.dict(sys.modules, {
                "chromadb": MagicMock(), "chromadb.config": MagicMock(),
                "sentence_transformers": MagicMock(),
            }):
                with patch("lifebook.indexer.Indexer", return_value=mock_indexer_inst):
                    with patch("lifebook.vector.VectorIndex", return_value=mock_vi):
                        bot.start()
        mock_indexer_inst.start.assert_called_once()
        bot.transport.start.assert_called_once_with(bot._handle_message)

    def test_start_indexer_fails(self):
        bot = _make_bot()
        mock_vi = MagicMock()
        with patch.dict(sys.modules, {
            "chromadb": MagicMock(), "chromadb.config": MagicMock(),
            "sentence_transformers": MagicMock(),
        }):
            with patch("lifebook.indexer.Indexer", side_effect=Exception("no chromadb")):
                with patch("lifebook.vector.VectorIndex", return_value=mock_vi):
                    bot.start()
        assert bot.indexer is None
        bot.transport.start.assert_called_once()

    def test_stop(self):
        bot = _make_bot()
        mock_indexer = MagicMock()
        bot.indexer = mock_indexer
        bot.stop()
        bot._thread_pool.shutdown.assert_called_once()
        mock_indexer.stop.assert_called_once()
        bot.transport.stop.assert_called_once()

    def test_stop_no_indexer(self):
        bot = _make_bot()
        bot.stop()
        bot._thread_pool.shutdown.assert_called_once()
        bot.transport.stop.assert_called_once()
