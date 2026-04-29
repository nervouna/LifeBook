"""MessageHandler: handles non-command Feishu messages (image, URL, text)."""
from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .config import Config
from .executor import ProcessResult
from .feishu_transport import FeishuTransport
from .image_processor import detect_mime_type
from .ingest import ingest_image, ingest_text, ingest_url

logger = logging.getLogger(__name__)

GENERIC_ERROR = "[LifeBook] 操作失败，请稍后重试。如果问题持续，请联系管理员。"


class MessageHandler:
    """Handles incoming non-command messages.

    Extracted from FeishuBot to separate message handling from command routing.
    """

    def __init__(
        self,
        transport: FeishuTransport,
        cfg: Config,
        thread_pool: ThreadPoolExecutor,
    ):
        self.transport = transport
        self.cfg = cfg
        self._thread_pool = thread_pool

    def handle_image_message(self, message_id: str, content_json: str) -> None:
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
        except Exception:
            logger.exception("ingest_image failed")
            self.transport.reply_text(message_id, "[LifeBook] 图片录入失败，请稍后重试。")
            return

        self.transport.reply_text(message_id, "[LifeBook] 已收到图片，开始加工…")
        self._thread_pool.submit(self._process_and_reply, message_id, [p])

    def handle_url_message(self, message_id: str, text: str, urls: list[str]) -> None:
        ingested_paths: list[Path] = []
        for url in urls:
            url = url.rstrip(").,;!?")
            try:
                p = ingest_url(self.cfg.knowledge, url, source_type="chat_link")
                ingested_paths.append(p)
            except Exception:
                logger.exception("ingest_url failed: %s", url)
                self.transport.reply_text(message_id, "[LifeBook] 链接录入失败，请稍后重试。")
                return

        if len(ingested_paths) == 1:
            ack = "[LifeBook] 已收到链接，开始加工…"
        else:
            ack = f"[LifeBook] 已收到 {len(ingested_paths)} 个链接，开始加工…"
        self.transport.reply_text(message_id, ack)
        self._thread_pool.submit(self._process_and_reply, message_id, ingested_paths)

    def handle_text_message(self, message_id: str, text: str) -> None:
        try:
            p = ingest_text(self.cfg.knowledge, text, source_type="chat_note")
        except Exception:
            logger.exception("ingest_text failed")
            self.transport.reply_text(message_id, "[LifeBook] 笔记录入失败，请稍后重试。")
            return

        self.transport.reply_text(message_id, "[LifeBook] 已收到笔记，开始加工…")
        self._thread_pool.submit(self._process_and_reply, message_id, [p])

    def _process_and_reply(self, message_id: str, paths: list[Path]) -> None:
        from .executor import Executor
        executor = Executor(self.cfg)
        results: list[ProcessResult] = []
        for p in paths:
            try:
                results.append(executor.process_file(p))
            except Exception:
                logger.exception("process_file failed: %s", p)
                results.append(ProcessResult(p, False, error="处理失败"))

        self.transport.reply_text(message_id, self._format_results(results))

    def _format_results(self, results: list[ProcessResult]) -> str:
        lines = []
        for r in results:
            if r.ok and r.topic_path:
                rel = r.topic_path.relative_to(self.cfg.knowledge.root)
                lines.append(f"✓ 已归档到 {rel}")
            elif r.skipped_reason:
                lines.append(f"⊘ 跳过：{r.skipped_reason}")
            else:
                lines.append(f"✗ 失败：{r.error}")
        return "\n".join(lines) if lines else "[LifeBook] 没有结果。"
