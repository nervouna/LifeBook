"""Feishu bot: thin coordinator delegating to CommandRouter and MessageHandler."""
from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

from lark_oapi.api.im.v1 import P2ImMessageReceiveV1

from .config import Config
from .executor import Executor
from .feishu_commands import CommandRouter
from .feishu_handler import MessageHandler
from .feishu_transport import FeishuTransport
from .store import NoteStore
from .writer import Writer

if TYPE_CHECKING:
    from .indexer import Indexer

logger = logging.getLogger(__name__)

URL_RE = re.compile(r"https?://[^\s　，,;；。！？]+", re.IGNORECASE)

BACKPRESSURE_CMDS = frozenset({"process", "update-index"})


def _extract_text(content_json: str) -> str:
    """Extract plain text from Feishu message content."""
    try:
        obj = json.loads(content_json)
    except Exception:
        return content_json
    if isinstance(obj, dict):
        return obj.get("text") or obj.get("content") or ""
    return str(obj)


def _strip_mentions(text: str, mentions: list | None) -> str:
    """Remove @bot mentions from the text."""
    if not mentions:
        return text.strip()
    for m in mentions:
        key = getattr(m, "key", None) or (m.get("key") if isinstance(m, dict) else None)
        if key:
            text = text.replace(key, "")
    return text.strip()


class FeishuBot:
    def __init__(
        self,
        cfg: Config,
        executor: Executor | None = None,
        transport: FeishuTransport | None = None,
    ):
        self.cfg = cfg
        self.store = NoteStore(cfg.knowledge)
        self.executor = executor or Executor(cfg, store=self.store)
        from .llm import LLMClient
        self.writer = Writer(cfg, LLMClient(cfg.llm), store=self.store)
        self.transport = transport or FeishuTransport(cfg.feishu)
        self.indexer: Indexer | None = None
        self._vector = None
        self._thread_pool = ThreadPoolExecutor(max_workers=4)
        self._in_flight: set[str] = set()

        self._cmd_router = CommandRouter(
            transport=self.transport,
            writer=self.writer,
            executor=self.executor,
            cfg=cfg,
        )
        self._msg_handler = MessageHandler(
            transport=self.transport,
            cfg=cfg,
            thread_pool=self._thread_pool,
        )

    # ---------- message handling ----------

    def _handle_message(self, data: P2ImMessageReceiveV1) -> None:
        event = data.event
        msg = event.message
        sender = event.sender

        if sender.sender_type != "user":
            return

        msg_type = msg.message_type
        message_id = msg.message_id

        logger.info("received msg_type=%s id=%s chat=%s", msg_type, msg_type, msg.chat_id)

        if msg_type == "image":
            self._msg_handler.handle_image_message(message_id, msg.content)
            return

        if msg_type != "text":
            self.transport.reply_text(message_id, f"[LifeBook] 暂不支持 {msg_type} 类型消息，请发送文字或链接。")
            return

        text = _extract_text(msg.content)
        text = _strip_mentions(text, msg.mentions)

        if not text:
            return

        stripped = text.strip()

        # --- Slash commands ---

        if stripped.startswith("/write"):
            idea = stripped[len("/write"):].strip()
            if not idea:
                self.transport.reply_text(
                    message_id,
                    "[LifeBook] 请提供写作想法，例如：/write 我想写一篇关于AI对创意工作影响的文章",
                )
                return
            self._thread_pool.submit(self._cmd_router.dispatch_write, message_id, idea)
            return

        if stripped.startswith("/publish") or stripped == "publish":
            force = stripped in ("/publish!", "/publish --force")
            self._thread_pool.submit(self._cmd_router.dispatch_publish, message_id, force)
            return

        if stripped in ("/restore", "restore"):
            self._thread_pool.submit(self._cmd_router.dispatch_restore, message_id)
            return

        if stripped in ("/process", "process"):
            if "process" in self._in_flight:
                self.transport.reply_text(message_id, "[LifeBook] 正在执行加工任务，请稍后再试。")
                return
            self._in_flight.add("process")
            self._thread_pool.submit(self._run_with_backpressure, "process", self._cmd_router.dispatch_process, message_id)
            return

        if stripped in ("/update-index", "update-index"):
            if "update-index" in self._in_flight:
                self.transport.reply_text(message_id, "[LifeBook] 正在执行索引更新，请稍后再试。")
                return
            self._in_flight.add("update-index")
            self._thread_pool.submit(self._run_with_backpressure, "update-index", self._cmd_router.dispatch_update_index, message_id, self.indexer)
            return

        if stripped.startswith("/search"):
            query = stripped[len("/search"):].strip()
            if not query:
                self.transport.reply_text(
                    message_id, "[LifeBook] 请提供搜索词，例如：/search AI对创意工作的影响"
                )
                return
            self._thread_pool.submit(self._cmd_router.dispatch_search, message_id, query, self._vector)
            return

        if stripped in ("/status", "status"):
            self._reply_status(message_id)
            return

        # --- Non-command messages ---

        if self.writer.active:
            self._thread_pool.submit(self._cmd_router.dispatch_writer_message, message_id, text)
            return

        urls = URL_RE.findall(text)
        if urls:
            self._msg_handler.handle_url_message(message_id, text, urls)
        else:
            self._msg_handler.handle_text_message(message_id, text)

    def _run_with_backpressure(self, cmd: str, fn, *args) -> None:
        """Run a command and remove it from in_flight when done."""
        try:
            fn(*args)
        finally:
            self._in_flight.discard(cmd)

    def _reply_status(self, message_id: str) -> None:
        inbox = self.store.scan_inbox()
        topic_count = self.store.topic_count()
        writing_status = f"\n  写作模式：{'进行中 (' + self.writer.stage + ')' if self.writer.active else '未启动'}"
        self.transport.reply_text(
            message_id,
            f"[LifeBook] 状态\n"
            f"  Inbox 待加工：{len(inbox)}\n"
            f"  已归档 Topics：{topic_count}\n"
            f"{writing_status}\n"
            f"  发送链接或文字即可录入\n"
            f"  发送 /process 手动加工 inbox\n"
            f"  发送 /write <想法> 进入写作模式",
        )

    # ---------- lifecycle ----------

    def start(self) -> None:
        try:
            from .indexer import Indexer
            self.indexer = Indexer(self.cfg)
            self.indexer.start()
            logger.info("Indexer background thread started")
        except Exception as e:
            logger.warning("Failed to start indexer: %s", e)
            self.indexer = None

        try:
            from .vector import VectorIndex
            persist_dir = self.cfg.knowledge.vector_store_path
            self._vector = VectorIndex(persist_dir)
            logger.info("VectorIndex initialized")
        except Exception as e:
            logger.warning("Failed to init VectorIndex: %s", e)
            self._vector = None

        self.transport.start(self._handle_message)

    def stop(self) -> None:
        self._thread_pool.shutdown(wait=False, cancel_futures=True)
        if self.indexer is not None:
            self.indexer.stop()
            logger.info("Indexer stopped")
        self.transport.stop()
