"""Feishu bot: long-connection WebSocket client that ingests messages."""
from __future__ import annotations

import json
import logging
import re
import threading
from pathlib import Path
from typing import Callable

import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    CreateMessageRequest,
    CreateMessageRequestBody,
    P2ImMessageReceiveV1,
    ReplyMessageRequest,
    ReplyMessageRequestBody,
)

from .config import Config
from .executor import Executor, ProcessResult
from .ingest import ingest_text, ingest_url
from .writer import Writer

logger = logging.getLogger(__name__)

URL_RE = re.compile(r"https?://[^\s\u3000，,;；。！？]+", re.IGNORECASE)


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
    def __init__(self, cfg: Config, executor: Executor | None = None):
        self.cfg = cfg
        self.executor = executor or Executor(cfg)
        from .llm import LLMClient
        self.writer = Writer(cfg, LLMClient(cfg.llm))
        self.api = (
            lark.Client.builder()
            .app_id(cfg.feishu.app_id)
            .app_secret(cfg.feishu.app_secret)
            .log_level(lark.LogLevel.WARNING)
            .build()
        )
        self._ws_client: lark.ws.Client | None = None

    # ---------- sending helpers ----------

    def send_text(self, chat_id: str, text: str) -> str | None:
        """Send a text message to a chat. Returns message_id on success."""
        body = (
            CreateMessageRequestBody.builder()
            .receive_id(chat_id)
            .msg_type("text")
            .content(json.dumps({"text": text}, ensure_ascii=False))
            .build()
        )
        req = (
            CreateMessageRequest.builder()
            .receive_id_type("chat_id")
            .request_body(body)
            .build()
        )
        resp = self.api.im.v1.message.create(req)
        if not resp.success():
            logger.error("send_text failed: %s %s", resp.code, resp.msg)
            return None
        return resp.data.message_id

    def reply_text(self, message_id: str, text: str) -> str | None:
        """Reply (threaded) to a specific message."""
        body = (
            ReplyMessageRequestBody.builder()
            .msg_type("text")
            .content(json.dumps({"text": text}, ensure_ascii=False))
            .build()
        )
        req = (
            ReplyMessageRequest.builder()
            .message_id(message_id)
            .request_body(body)
            .build()
        )
        resp = self.api.im.v1.message.reply(req)
        if not resp.success():
            logger.error("reply_text failed: %s %s", resp.code, resp.msg)
            return None
        return resp.data.message_id

    # ---------- message handling ----------

    def _handle_message(self, data: P2ImMessageReceiveV1) -> None:
        event = data.event
        msg = event.message
        sender = event.sender

        # Only accept real users (skip bots, system messages)
        if sender.sender_type != "user":
            return

        msg_type = msg.message_type
        message_id = msg.message_id
        chat_id = msg.chat_id

        logger.info("received msg_type=%s id=%s chat=%s", msg_type, message_id, chat_id)

        if msg_type != "text":
            self.reply_text(message_id, f"[LifeBook] 暂不支持 {msg_type} 类型消息，请发送文字或链接。")
            return

        text = _extract_text(msg.content)
        text = _strip_mentions(text, msg.mentions)

        if not text:
            return

        stripped = text.strip()

        # --- Slash commands (always take priority, even in writing mode) ---

        # Command: /write <idea>
        if stripped.startswith("/write"):
            idea = stripped[len("/write"):].strip()
            if not idea:
                self.reply_text(message_id, "[LifeBook] 请提供写作想法，例如：/write 我想写一篇关于AI对创意工作影响的文章")
                return
            threading.Thread(target=self._run_write_cmd, args=(message_id, idea), daemon=True).start()
            return

        # Command: /publish
        if stripped in ("/publish", "publish"):
            threading.Thread(target=self._run_publish_cmd, args=(message_id,), daemon=True).start()
            return

        # Command: /process
        if stripped in ("/process", "process"):
            threading.Thread(target=self._run_process_cmd, args=(message_id,), daemon=True).start()
            return

        # Command: /status
        if stripped in ("/status", "status"):
            self._reply_status(message_id)
            return

        # --- Non-command messages ---

        # Writing mode: all messages route to Writer
        if self.writer.active:
            threading.Thread(target=self._run_writer_msg, args=(message_id, text), daemon=True).start()
            return

        # Detect URLs in the message
        urls = URL_RE.findall(text)
        if urls:
            self._handle_url_message(message_id, text, urls)
        else:
            self._handle_text_message(message_id, text)

    def _handle_url_message(self, message_id: str, text: str, urls: list[str]) -> None:
        ingested_paths: list[Path] = []
        for url in urls:
            # Strip trailing punctuation that the regex might have missed
            url = url.rstrip(").,;!?")
            try:
                p = ingest_url(self.cfg.knowledge, url, source_type="chat_link")
                ingested_paths.append(p)
            except Exception as e:
                logger.exception("ingest_url failed: %s", url)
                self.reply_text(message_id, f"[LifeBook] 录入失败：{url}\n错误：{e}")
                return

        # Immediate ack
        if len(ingested_paths) == 1:
            ack = f"[LifeBook] 已收到链接，开始加工…"
        else:
            ack = f"[LifeBook] 已收到 {len(ingested_paths)} 个链接，开始加工…"
        self.reply_text(message_id, ack)

        # Async process in background
        threading.Thread(
            target=self._process_and_reply,
            args=(message_id, ingested_paths),
            daemon=True,
        ).start()

    def _handle_text_message(self, message_id: str, text: str) -> None:
        try:
            p = ingest_text(self.cfg.knowledge, text, source_type="chat_note")
        except Exception as e:
            logger.exception("ingest_text failed")
            self.reply_text(message_id, f"[LifeBook] 录入失败：{e}")
            return

        self.reply_text(message_id, "[LifeBook] 已收到笔记，开始加工…")
        threading.Thread(
            target=self._process_and_reply,
            args=(message_id, [p]),
            daemon=True,
        ).start()

    def _process_and_reply(self, message_id: str, paths: list[Path]) -> None:
        results: list[ProcessResult] = []
        for p in paths:
            try:
                results.append(self.executor.process_file(p))
            except Exception as e:
                logger.exception("process_file failed: %s", p)
                results.append(ProcessResult(p, False, error=str(e)))

        self.reply_text(message_id, self._format_results(results))

    def _run_process_cmd(self, message_id: str) -> None:
        results = self.executor.process_inbox()
        if not results:
            self.reply_text(message_id, "[LifeBook] Inbox 为空，没有待加工条目。")
            return
        self.reply_text(message_id, self._format_results(results, show_summary=True))

    def _format_results(self, results: list[ProcessResult], show_summary: bool = False) -> str:
        lines = []
        if show_summary:
            ok = sum(1 for r in results if r.ok)
            sk = sum(1 for r in results if r.skipped_reason)
            fl = len(results) - ok - sk
            lines.append(f"[LifeBook] 加工完成：{ok} 成功 / {sk} 跳过 / {fl} 失败\n")

        for r in results:
            if r.ok and r.topic_path:
                rel = r.topic_path.relative_to(self.cfg.knowledge.root)
                lines.append(f"✓ 已归档到 {rel}")
            elif r.skipped_reason:
                lines.append(f"⊘ 跳过：{r.skipped_reason}")
            else:
                lines.append(f"✗ 失败：{r.error}")
        return "\n".join(lines) if lines else "[LifeBook] 没有结果。"

    def _reply_status(self, message_id: str) -> None:
        inbox = self.executor.scan_inbox()
        topics_dir = self.cfg.knowledge.topics_path
        topic_count = sum(1 for _ in topics_dir.rglob("*.md")) if topics_dir.exists() else 0
        writing_status = f"\n  写作模式：{'进行中 (' + self.writer.stage + ')' if self.writer.active else '未启动'}"
        self.reply_text(
            message_id,
            f"[LifeBook] 状态\n"
            f"  Inbox 待加工：{len(inbox)}\n"
            f"  已归档 Topics：{topic_count}\n"
            f"{writing_status}\n"
            f"  发送链接或文字即可录入\n"
            f"  发送 /process 手动加工 inbox\n"
            f"  发送 /write <想法> 进入写作模式",
        )

    def _run_write_cmd(self, message_id: str, idea: str) -> None:
        try:
            reply = self.writer.start(idea)
        except Exception as e:
            logger.exception("writer.start failed")
            reply = f"[LifeBook] 写作启动失败：{e}"
        self.reply_text(message_id, reply)

    def _run_publish_cmd(self, message_id: str) -> None:
        try:
            reply = self.writer.publish()
        except Exception as e:
            logger.exception("writer.publish failed")
            reply = f"[LifeBook] 发布失败：{e}"
        self.reply_text(message_id, reply)

    def _run_writer_msg(self, message_id: str, text: str) -> None:
        try:
            reply = self.writer.handle_message(text)
        except Exception as e:
            logger.exception("writer.handle_message failed")
            reply = f"[LifeBook] 写作处理失败：{e}"
        self.reply_text(message_id, reply)

    # ---------- lifecycle ----------

    def start(self) -> None:
        handler = (
            lark.EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(self._handle_message)
            .build()
        )
        self._ws_client = lark.ws.Client(
            app_id=self.cfg.feishu.app_id,
            app_secret=self.cfg.feishu.app_secret,
            event_handler=handler,
            log_level=lark.LogLevel.WARNING,
        )
        logger.info("Feishu bot starting (long-connection WebSocket)...")
        self._ws_client.start()
