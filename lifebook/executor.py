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
)
from .prompts import build_extract_system, build_extract_tool_schema
from .store import NoteStore

logger = logging.getLogger(__name__)

STANDARD_SOURCE_FIELDS = frozenset({
    "status", "source", "source_type", "created", "title",
    "fetch_error", "fetch_at", "fetch_via", "fetched_at",
    "processing_at", "processed_at", "topic_ref", "tags",
    "category", "llm_draft", "skip_reason",
})


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
        self._valid_categories: set[str] = set(cfg.knowledge.categories)
        self._extract_schema = build_extract_tool_schema(cfg.knowledge.categories)
        self._extract_system = build_extract_system(cfg.knowledge.categories)

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

        url = post.get("source") or ""
        content = post.content.strip()

        if url:
            existing = self.store.find_by_source_url(url)
            if existing:
                logger.info("  skip: duplicate source_url -> %s", existing.name)
                post["status"] = "skipped"
                post["skip_reason"] = f"duplicate of {existing.name}"
                self.store.write_note(source_path, post)
                return ProcessResult(
                    source_path, False,
                    skipped_reason=f"duplicate source_url: {existing.name}",
                )

        if url and not content:
            fr = self.fetcher.fetch(url)
            if not fr.ok:
                post["status"] = fr.status
                post["fetch_error"] = fr.error or ""
                post["fetch_at"] = now_iso()
                self.store.write_note(source_path, post)
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
            self.store.write_note(source_path, post)

        if not content:
            return ProcessResult(source_path, False, error="no content to process")

        # 2. Ask LLM to extract
        extra_meta = {k: v for k, v in post.metadata.items()
                      if k not in STANDARD_SOURCE_FIELDS}
        existing_categories = [
            c for c in self.store.existing_categories()
            if c in self._valid_categories
        ]
        user_prompt = self._build_extract_prompt(
            title_hint=post.get("title") or "",
            url=url,
            content=content,
            existing_categories=existing_categories,
            extra_meta=extra_meta,
        )
        try:
            extracted = self.llm.structured_call(
                tool_name="extract_note",
                tool_description="把一段原始素材加工成结构化的知识笔记。",
                input_schema=self._extract_schema,
                user_prompt=user_prompt,
                system=self._extract_system,
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
            self.store.write_note(source_path, post)
            return ProcessResult(
                source_path, False,
                skipped_reason=f"low confidence {conf}",
            )

        # 3.5. Validate category and sanitize tags
        cat = extracted.get("category", "")
        if cat not in self._valid_categories:
            logger.error("invalid category %r for %s", cat, source_path.name)
            return ProcessResult(
                source_path, False,
                error=f"invalid category: {cat}",
            )
        extracted["tags"] = sanitize_tags(extracted.get("tags", []))
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
        alt_cat = extracted.get("alt_category")
        if alt_cat and alt_cat in self._valid_categories:
            topic_meta["alt_category"] = alt_cat
        topic_meta = {k: v for k, v in topic_meta.items() if v is not None}
        for k, v in extra_meta.items():
            topic_meta[f"source_{k}"] = v

        topic_dir = self.cfg.knowledge.topics_path / extracted["category"]
        stem = slugify(extracted["title"])
        topic_path = unique_path(topic_dir, stem)
        aliases: list[str] = []
        if stem != extracted["title"]:
            aliases.append(extracted["title"])
        if aliases:
            topic_meta["aliases"] = aliases
        self.store.write_note(topic_path, new_post(topic_body, **topic_meta))

        # 6. Update source file
        post["status"] = "processed"
        post["processed_at"] = now_iso()
        post["topic_ref"] = str(topic_path.relative_to(self.cfg.knowledge.root))
        post["tags"] = extracted["tags"]
        post["category"] = extracted["category"]
        self.store.write_note(source_path, post)

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
        extra_meta: dict[str, str] | None = None,
    ) -> str:
        cats = "、".join(existing_categories) if existing_categories else "（暂无，请新建）"
        header = []
        if title_hint:
            header.append(f"原标题：{title_hint}")
        if url:
            header.append(f"来源 URL：{url}")
        header.append(f"现有目录：{cats}")
        if extra_meta:
            meta_lines = "\n".join(f"- {k}: {v}" for k, v in extra_meta.items())
            header.append(f"来源提供的结构化元数据：\n{meta_lines}")
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
