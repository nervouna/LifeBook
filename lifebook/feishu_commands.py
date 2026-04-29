"""CommandRouter: dispatches Feishu slash commands to the appropriate handlers."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from .config import Config
from .executor import Executor, ProcessResult
from .feishu_transport import FeishuTransport

if TYPE_CHECKING:
    from .indexer import Indexer
    from .vector import VectorIndex
    from .writer import Writer

logger = logging.getLogger(__name__)

GENERIC_ERROR = "[LifeBook] 操作失败，请稍后重试。如果问题持续，请联系管理员。"


class CommandRouter:
    """Routes slash commands to their implementations.

    Extracted from FeishuBot to separate command logic from message routing.
    """

    def __init__(
        self,
        transport: FeishuTransport,
        writer: Writer,
        executor: Executor,
        cfg: Config | None = None,
    ):
        self.transport = transport
        self.writer = writer
        self.executor = executor
        self.cfg = cfg

    def dispatch_write(self, message_id: str, idea: str) -> None:
        if not idea:
            self.transport.reply_text(
                message_id,
                "[LifeBook] 请提供写作想法，例如：/write 我想写一篇关于AI对创意工作影响的文章",
            )
            return
        try:
            reply = self.writer.start(idea)
        except Exception:
            logger.exception("writer.start failed")
            reply = GENERIC_ERROR
        self.transport.reply_text(message_id, reply)

    def dispatch_publish(self, message_id: str, force: bool = False) -> None:
        try:
            reply = self.writer.publish(force=force)
        except Exception:
            logger.exception("writer.publish failed")
            reply = GENERIC_ERROR
        self.transport.reply_text(message_id, reply)

    def dispatch_restore(self, message_id: str) -> None:
        try:
            reply = self.writer.restore_draft()
        except Exception:
            logger.exception("writer.restore_draft failed")
            reply = GENERIC_ERROR
        self.transport.reply_text(message_id, reply)

    def dispatch_process(self, message_id: str) -> None:
        results = self.executor.process_inbox()
        if not results:
            self.transport.reply_text(message_id, "[LifeBook] Inbox 为空，没有待加工条目。")
            return
        self.transport.reply_text(message_id, self._format_results(results, show_summary=True))

    def dispatch_update_index(self, message_id: str, indexer: Indexer | None = None) -> None:
        try:
            if indexer is None:
                self.transport.reply_text(message_id, "[LifeBook] 索引器未初始化，请稍后重试")
                return
            stats = indexer.incremental_update()

            upserted = stats.get("upserted", 0)
            deleted = stats.get("deleted", 0)
            unchanged = stats.get("unchanged", 0)
            errors = stats.get("errors", 0)

            reply = f"[LifeBook] 向量索引更新完成\n"
            reply += f"  新增/更新: {upserted}\n"
            reply += f"  删除: {deleted}\n"
            reply += f"  未变化: {unchanged}\n"
            if errors:
                reply += f"  错误: {errors} 个\n"

        except Exception:
            logger.exception("update-index failed")
            reply = GENERIC_ERROR

        self.transport.reply_text(message_id, reply)

    def dispatch_search(self, message_id: str, query: str, vector: VectorIndex | None = None) -> None:
        if not query:
            self.transport.reply_text(
                message_id, "[LifeBook] 请提供搜索词，例如：/search AI对创意工作的影响"
            )
            return

        try:
            if vector is None:
                from .vector import VectorIndex
                persist_dir = self.cfg.knowledge.vector_store_path
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

        except Exception:
            logger.exception("search failed")
            reply = GENERIC_ERROR

        self.transport.reply_text(message_id, reply)

    def dispatch_writer_message(self, message_id: str, text: str) -> None:
        try:
            reply = self.writer.handle_message(text)
        except Exception:
            logger.exception("writer.handle_message failed")
            reply = GENERIC_ERROR
        self.transport.reply_text(message_id, reply)

    def _format_results(self, results: list[ProcessResult], show_summary: bool = False) -> str:
        lines = []
        if show_summary:
            ok = sum(1 for r in results if r.ok)
            sk = sum(1 for r in results if r.skipped_reason)
            fl = len(results) - ok - sk
            lines.append(f"[LifeBook] 加工完成：{ok} 成功 / {sk} 跳过 / {fl} 失败\n")

        for r in results:
            if r.ok and r.topic_path:
                if self.cfg and self.cfg.knowledge:
                    rel = r.topic_path.relative_to(self.cfg.knowledge.root)
                else:
                    rel = r.topic_path
                lines.append(f"✓ 已归档到 {rel}")
            elif r.skipped_reason:
                lines.append(f"⊘ 跳过：{r.skipped_reason}")
            else:
                lines.append(f"✗ 失败：{r.error}")
        return "\n".join(lines) if lines else "[LifeBook] 没有结果。"
