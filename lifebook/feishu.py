"""Feishu bot: command routing and business logic."""
from __future__ import annotations

import json
import logging
import re
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from lark_oapi.api.im.v1 import P2ImMessageReceiveV1

from .config import Config
from .executor import Executor, ProcessResult
from .feishu_transport import FeishuTransport
from .image_processor import detect_mime_type
from .ingest import ingest_image, ingest_text, ingest_url
from .store import NoteStore
from .writer import Writer

if TYPE_CHECKING:
    from .indexer import Indexer

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

    # ---------- message handling ----------

    def _handle_message(self, data: P2ImMessageReceiveV1) -> None:
        event = data.event
        msg = event.message
        sender = event.sender

        if sender.sender_type != "user":
            return

        msg_type = msg.message_type
        message_id = msg.message_id
        chat_id = msg.chat_id

        logger.info("received msg_type=%s id=%s chat=%s", msg_type, message_id, chat_id)

        if msg_type == "image":
            self._handle_image_message(message_id, msg.content)
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
                self.transport.reply_text(message_id, "[LifeBook] 请提供写作想法，例如：/write 我想写一篇关于AI对创意工作影响的文章")
                return
            threading.Thread(target=self._run_write_cmd, args=(message_id, idea), daemon=True).start()
            return

        if stripped.startswith("/publish") or stripped == "publish":
            force = stripped in ("/publish!", "/publish --force")
            threading.Thread(target=self._run_publish_cmd, args=(message_id, force), daemon=True).start()
            return

        if stripped in ("/restore", "restore"):
            threading.Thread(target=self._run_restore_cmd, args=(message_id,), daemon=True).start()
            return

        if stripped in ("/process", "process"):
            threading.Thread(target=self._run_process_cmd, args=(message_id,), daemon=True).start()
            return

        if stripped in ("/update-index", "update-index"):
            threading.Thread(target=self._run_update_index_cmd, args=(message_id,), daemon=True).start()
            return

        if stripped.startswith("/search"):
            query = stripped[len("/search"):].strip()
            if not query:
                self.transport.reply_text(message_id, "[LifeBook] 请提供搜索词，例如：/search AI对创意工作的影响")
                return
            threading.Thread(target=self._run_search_cmd, args=(message_id, query), daemon=True).start()
            return

        if stripped in ("/status", "status"):
            self._reply_status(message_id)
            return

        # --- Non-command messages ---

        if self.writer.active:
            threading.Thread(target=self._run_writer_msg, args=(message_id, text), daemon=True).start()
            return

        urls = URL_RE.findall(text)
        if urls:
            self._handle_url_message(message_id, text, urls)
        else:
            self._handle_text_message(message_id, text)

    def _handle_image_message(self, message_id: str, content_json: str) -> None:
        """Download the image from Feishu and ingest it for processing."""
        try:
            content_obj = json.loads(content_json)
        except Exception:
            content_obj = {}
        image_key = content_obj.get("image_key") or ""
        if not image_key:
            self.transport.reply_text(message_id, "[LifeBook] 图片消息缺少 image_key，无法下载。")
            return

        image_bytes = self.transport.download_image_message(message_id, image_key)
        if not image_bytes:
            self.transport.reply_text(message_id, "[LifeBook] 图片下载失败，请稍后重试。")
            return

        try:
            mime_type = detect_mime_type(image_bytes)
            p = ingest_image(
                self.cfg.knowledge,
                image_bytes=image_bytes,
                mime_type=mime_type,
            )
        except Exception as e:
            logger.exception("ingest_image failed")
            self.transport.reply_text(message_id, f"[LifeBook] 图片录入失败：{e}")
            return

        self.transport.reply_text(message_id, "[LifeBook] 已收到图片，开始加工…")
        threading.Thread(
            target=self._process_and_reply,
            args=(message_id, [p]),
            daemon=True,
        ).start()

    def _handle_url_message(self, message_id: str, text: str, urls: list[str]) -> None:
        ingested_paths: list[Path] = []
        for url in urls:
            url = url.rstrip(").,;!?")
            try:
                p = ingest_url(self.cfg.knowledge, url, source_type="chat_link")
                ingested_paths.append(p)
            except Exception as e:
                logger.exception("ingest_url failed: %s", url)
                self.transport.reply_text(message_id, f"[LifeBook] 录入失败：{url}\n错误：{e}")
                return

        if len(ingested_paths) == 1:
            ack = f"[LifeBook] 已收到链接，开始加工…"
        else:
            ack = f"[LifeBook] 已收到 {len(ingested_paths)} 个链接，开始加工…"
        self.transport.reply_text(message_id, ack)

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
            self.transport.reply_text(message_id, f"[LifeBook] 录入失败：{e}")
            return

        self.transport.reply_text(message_id, "[LifeBook] 已收到笔记，开始加工…")
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

        self.transport.reply_text(message_id, self._format_results(results))

    def _run_process_cmd(self, message_id: str) -> None:
        results = self.executor.process_inbox()
        if not results:
            self.transport.reply_text(message_id, "[LifeBook] Inbox 为空，没有待加工条目。")
            return
        self.transport.reply_text(message_id, self._format_results(results, show_summary=True))

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

    def _run_write_cmd(self, message_id: str, idea: str) -> None:
        try:
            reply = self.writer.start(idea)
        except Exception as e:
            logger.exception("writer.start failed")
            reply = f"[LifeBook] 写作启动失败：{e}"
        self.transport.reply_text(message_id, reply)

    def _run_publish_cmd(self, message_id: str, force: bool = False) -> None:
        try:
            reply = self.writer.publish(force=force)
        except Exception as e:
            logger.exception("writer.publish failed")
            reply = f"[LifeBook] 发布失败：{e}"
        self.transport.reply_text(message_id, reply)

    def _run_writer_msg(self, message_id: str, text: str) -> None:
        try:
            reply = self.writer.handle_message(text)
        except Exception as e:
            logger.exception("writer.handle_message failed")
            reply = f"[LifeBook] 写作处理失败：{e}"
        self.transport.reply_text(message_id, reply)

    def _run_restore_cmd(self, message_id: str) -> None:
        try:
            reply = self.writer.restore_draft()
        except Exception as e:
            logger.exception("writer.restore_draft failed")
            reply = f"[LifeBook] 恢复失败：{e}"
        self.transport.reply_text(message_id, reply)

    def _run_update_index_cmd(self, message_id: str) -> None:
        try:
            from .indexer import Indexer
            indexer = Indexer(self.cfg)
            stats = indexer.incremental_update()

            upserted = stats.get("upserted", 0)
            deleted = stats.get("deleted", 0)
            unchanged = stats.get("unchanged", 0)
            errors = stats.get("errors", [])

            reply = f"[LifeBook] 向量索引更新完成\n"
            reply += f"  新增/更新: {upserted}\n"
            reply += f"  删除: {deleted}\n"
            reply += f"  未变化: {unchanged}\n"
            if errors:
                reply += f"  错误: {len(errors)} 个\n"
                for err in errors[:3]:
                    reply += f"    - {err}\n"
                if len(errors) > 3:
                    reply += f"    ... 还有 {len(errors) - 3} 个错误\n"

        except Exception as e:
            logger.exception("update-index failed")
            reply = f"[LifeBook] 索引更新失败：{e}"

        self.transport.reply_text(message_id, reply)

    def _run_search_cmd(self, message_id: str, query: str) -> None:
        try:
            from .vector import VectorIndex
            persist_dir = self.cfg.knowledge.state_path / "vector_store"
            vector = VectorIndex(persist_dir)
            results = vector.search(query, n_results=5)

            if not results:
                self.transport.reply_text(message_id, f"[LifeBook] 未找到与 '{query}' 相关的内容")
                return

            reply = f"[LifeBook] 搜索 '{query}' 结果（显示前 {len(results)} 个）:\n\n"
            for i, r in enumerate(results, 1):
                title = r.metadata.get("title", r.doc_id)
                similarity = max(0, 1.0 - r.distance) * 100
                preview = r.text[:100] + "..." if len(r.text) > 100 else r.text

                reply += f"{i}. {title}\n"
                reply += f"   相似度: {similarity:.1f}%\n"
                reply += f"   路径: {r.doc_id}\n"
                reply += f"   摘要: {preview}\n\n"

        except Exception as e:
            logger.exception("search failed")
            reply = f"[LifeBook] 搜索失败：{e}"

        self.transport.reply_text(message_id, reply)

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

        self.transport.start(self._handle_message)

    def stop(self) -> None:
        if self.indexer is not None:
            self.indexer.stop()
            logger.info("Indexer stopped")
        self.transport.stop()
