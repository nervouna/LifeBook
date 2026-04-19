"""Executor: process inbox files into topic notes."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from .config import Config
from .fetcher import Fetcher
from .llm import LLMClient
from .notes import (
    new_post,
    now_iso,
    sanitize_tags,
    slugify,
    unique_path,
    wikilink_text,
    write_note,
)
from .prompts import EXTRACT_SYSTEM, EXTRACT_TOOL_SCHEMA
from .store import NoteStore

logger = logging.getLogger(__name__)


@dataclass
class ProcessResult:
    source_path: Path
    ok: bool
    topic_path: Path | None = None
    error: str | None = None
    skipped_reason: str | None = None


class Executor:
    def __init__(self, cfg: Config, store: NoteStore | None = None):
        self.cfg = cfg
        self.store = store or NoteStore(cfg.knowledge)
        self.llm = LLMClient(cfg.llm)
        self.fetcher = Fetcher(cfg.tavily, cfg.fetch)

    # ---------- public API ----------

    def recover_stale(self, timeout_minutes: int = 10, dry_run: bool = False) -> list[tuple[Path, str]]:
        """Roll back files stuck in `status: processing` for longer than timeout."""
        return self.store.recover_stale(timeout_minutes, dry_run)

    def scan_inbox(self) -> list[Path]:
        """List all source files with status: inbox."""
        return self.store.scan_inbox()

    def process_file(self, source_path: Path) -> ProcessResult:
        """Process a single source file end-to-end."""
        logger.info("process: %s", source_path.name)
        try:
            claimed, post = self.store.claim_for_processing(source_path)
        except Exception as e:
            return ProcessResult(source_path, False, error=f"read failed: {e}")
        if not claimed:
            logger.info("  skip: already %s", post.get("status") if post else "?")
            return ProcessResult(
                source_path, False,
                skipped_reason=f"already {post.get('status') if post else 'claimed'}",
            )

        # 1. Ensure we have content (fetch URL if needed)
        url = post.get("source") or ""
        content = post.content.strip()
        if url and not content:
            fr = self.fetcher.fetch(url)
            if not fr.ok:
                post["status"] = fr.status
                post["fetch_error"] = fr.error or ""
                post["fetch_at"] = now_iso()
                write_note(source_path, post)
                return ProcessResult(
                    source_path, False,
                    skipped_reason=f"{fr.status}: {fr.error}",
                )
            content = fr.content
            post.content = content
            if fr.title and not post.get("title"):
                post["title"] = fr.title
            post["fetch_via"] = fr.via
            post["fetched_at"] = now_iso()
            write_note(source_path, post)

        if not content:
            return ProcessResult(source_path, False, error="no content to process")

        # 2. Ask LLM to extract
        existing_categories = self.store.existing_categories()
        user_prompt = self._build_extract_prompt(
            title_hint=post.get("title") or "",
            url=url,
            content=content,
            existing_categories=existing_categories,
        )
        try:
            extracted = self.llm.structured_call(
                tool_name="extract_note",
                tool_description="把一段原始素材加工成结构化的知识笔记。",
                input_schema=EXTRACT_TOOL_SCHEMA,
                user_prompt=user_prompt,
                system=EXTRACT_SYSTEM,
            )
        except Exception as e:
            logger.exception("LLM extract failed for %s", source_path)
            return ProcessResult(source_path, False, error=f"LLM failed: {e}")

        # 3. Low confidence -> skipped
        conf = float(extracted.get("confidence", 0))
        if conf < self.cfg.executor.classify_min_confidence:
            post["status"] = "skipped"
            post["skip_reason"] = f"low confidence: {conf}"
            post["llm_draft"] = extracted
            write_note(source_path, post)
            return ProcessResult(
                source_path, False,
                skipped_reason=f"low confidence {conf}",
            )

        # 3.5. Sanitize tags
        extracted["tags"] = sanitize_tags(extracted.get("tags", []))
        cat = extracted.get("category", "")
        if cat:
            extracted["tags"] = [t for t in extracted["tags"] if t != cat]

        # 4. Find related topic notes and inject [[links]]
        related_links = self.store.find_related(extracted.get("related_keywords", []))
        narrative = extracted["narrative"]
        if related_links:
            narrative = narrative.rstrip() + "\n\n## 相关笔记\n\n" + "\n".join(
                f"- [[{wikilink_text(lk)}]]" for lk in related_links
            )

        # 5. Assemble topic note
        topic_body = self._compose_topic_body(
            summary=extracted["summary"],
            key_points=extracted["key_points"],
            narrative=narrative,
            source_url=url,
        )

        topic_meta = {
            "title": extracted["title"],
            "created": post.get("created") or now_iso(),
            "processed_at": now_iso(),
            "source_ref": str(source_path.relative_to(self.cfg.knowledge.root)),
            "source_url": url or None,
            "tags": extracted["tags"],
            "category": extracted["category"],
            "related_keywords": extracted["related_keywords"],
            "confidence": conf,
            "status": "active",
        }
        topic_meta = {k: v for k, v in topic_meta.items() if v is not None}

        topic_dir = self.cfg.knowledge.topics_path / extracted["category"]
        stem = slugify(extracted["title"])
        topic_path = unique_path(topic_dir, stem)
        aliases: list[str] = []
        if stem != extracted["title"]:
            aliases.append(extracted["title"])
        if aliases:
            topic_meta["aliases"] = aliases
        write_note(topic_path, new_post(topic_body, **topic_meta))

        # 6. Update source file
        post["status"] = "processed"
        post["processed_at"] = now_iso()
        post["topic_ref"] = str(topic_path.relative_to(self.cfg.knowledge.root))
        post["tags"] = extracted["tags"]
        post["category"] = extracted["category"]
        write_note(source_path, post)

        logger.info("  -> %s", topic_path.relative_to(self.cfg.knowledge.root))
        return ProcessResult(source_path, True, topic_path=topic_path)

    def process_inbox(self) -> list[ProcessResult]:
        files = self.scan_inbox()
        limit = self.cfg.executor.batch_limit
        if len(files) > limit:
            logger.info("inbox has %d, processing first %d", len(files), limit)
            files = files[:limit]
        results = []
        for p in files:
            results.append(self.process_file(p))
        return results

    # ---------- helpers ----------

    def _build_extract_prompt(
        self,
        title_hint: str,
        url: str,
        content: str,
        existing_categories: list[str],
    ) -> str:
        cats = "、".join(existing_categories) if existing_categories else "（暂无，请新建）"
        header = []
        if title_hint:
            header.append(f"原标题：{title_hint}")
        if url:
            header.append(f"来源 URL：{url}")
        header.append(f"现有目录：{cats}")
        header_text = "\n".join(header)
        max_chars = 60000
        if len(content) > max_chars:
            content = content[:max_chars] + "\n\n[...内容过长已截断...]"
        return f"{header_text}\n\n---\n\n原始素材：\n\n{content}"

    def _compose_topic_body(
        self,
        summary: str,
        key_points: list[str],
        narrative: str,
        source_url: str,
    ) -> str:
        parts = [f"> {summary}\n"]
        parts.append("## 要点\n")
        for kp in key_points:
            parts.append(f"- {kp}")
        parts.append("")
        parts.append(narrative.strip())
        if source_url:
            parts.append("")
            parts.append(f"## 来源\n\n<{source_url}>")
        return "\n".join(parts) + "\n"
