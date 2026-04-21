"""Executor: process inbox files into topic notes."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from .config import Config
from .fetcher import Fetcher
from .image_processor import ImageData, compress_image
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
    "image_path", "image_hash", "image_mime",
    "image_original_bytes", "image_compressed_bytes",
    "image_width", "image_height",
})


@dataclass
class ProcessResult:
    source_path: Path
    ok: bool
    topic_path: Path | None = None
    error: str | None = None
    skipped_reason: str | None = None


class Executor:
    def __init__(
        self,
        cfg: Config,
        store: NoteStore | None = None,
        llm: LLMClient | None = None,
        fetcher: Fetcher | None = None,
    ):
        self.cfg = cfg
        self.store = store or NoteStore(cfg.knowledge)
        self.llm = llm or LLMClient(cfg.llm)
        self.vision_llm = LLMClient(cfg.vision) if cfg.vision else None
        self.fetcher = fetcher or Fetcher(cfg.tavily, cfg.fetch)
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

        # Step 1: claim
        post, err = self._claim(source_path)
        if err:
            return err

        # Route image source_type to dedicated branch
        if post.get("source_type") == "image":
            return self._process_image_file(source_path, post)

        url = post.get("source") or ""
        content = post.content.strip()

        # Step 2: duplicate check
        dup_err = self._check_duplicate(url, post, source_path)
        if dup_err:
            return dup_err

        # Step 3: fetch if needed
        content, fetch_err = self._fetch_if_needed(url, content, post, source_path)
        if fetch_err:
            return fetch_err
        if not content:
            return ProcessResult(source_path, False, error="no content to process")

        # Step 4: LLM extract
        extracted, llm_err = self._extract(content, post, source_path)
        if llm_err:
            return llm_err

        # Step 5: validate
        conf = float(extracted.get("confidence", 0))
        val_err = self._validate(extracted, conf, post, source_path)
        if val_err:
            return val_err

        # Step 6: link + compose topic
        extra_meta = {k: v for k, v in post.metadata.items()
                      if k not in STANDARD_SOURCE_FIELDS}
        topic_body = self._compose_topic_body(
            summary=extracted["summary"],
            key_points=extracted["key_points"],
            narrative=self._link_related(extracted),
            source_url=url,
        )

        # Step 7: write topic
        topic_path = self._write_topic(extracted, conf, source_path, url, extra_meta, topic_body)

        # Step 8: update source
        self._mark_processed(source_path, post, topic_path, extracted)

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

    # ---------- pipeline steps ----------

    def _process_image_file(self, source_path: Path, post: Any) -> ProcessResult:
        """Process an image source file: compress, extract, write topic."""
        image_path_rel = post.get("image_path") or ""
        if not image_path_rel:
            return ProcessResult(source_path, False, error="missing image_path metadata")

        full_image_path = self.cfg.knowledge.root / image_path_rel
        if not full_image_path.exists():
            return ProcessResult(source_path, False, error=f"image file not found: {image_path_rel}")

        try:
            image_bytes = full_image_path.read_bytes()
        except OSError as e:
            return ProcessResult(source_path, False, error=f"cannot read image: {e}")

        try:
            img_data = compress_image(image_bytes, self.cfg.image)
        except Exception as e:
            return ProcessResult(source_path, False, error=f"image compression failed: {e}")

        post["image_original_bytes"] = img_data.original_size
        post["image_compressed_bytes"] = img_data.compressed_size
        post["image_width"] = img_data.width
        post["image_height"] = img_data.height
        self.store.write_note(source_path, post)

        extracted, llm_err = self._extract_image(img_data, post, source_path)
        if llm_err:
            return llm_err

        conf = float(extracted.get("confidence", 0))
        val_err = self._validate(extracted, conf, post, source_path)
        if val_err:
            return val_err

        extra_meta = {k: v for k, v in post.metadata.items()
                      if k not in STANDARD_SOURCE_FIELDS}
        topic_body = self._compose_topic_body(
            summary=extracted["summary"],
            key_points=extracted["key_points"],
            narrative=self._link_related(extracted),
            source_url="",
        )
        topic_path = self._write_topic(extracted, conf, source_path, "", extra_meta, topic_body)
        self._mark_processed(source_path, post, topic_path, extracted)

        logger.info("  -> %s", topic_path.relative_to(self.cfg.knowledge.root))
        return ProcessResult(source_path, True, topic_path=topic_path)

    def _extract_image(
        self, img_data: ImageData, post: Any, source_path: Path,
    ) -> tuple[dict, ProcessResult | None]:
        """Extract structured data from an image via vision LLM."""
        existing_categories = [
            c for c in self.store.existing_categories()
            if c in self._valid_categories
        ]
        caption = post.content.strip() if post.content else ""
        user_prompt = self._build_image_extract_prompt(
            title_hint=post.get("title") or "",
            caption=caption,
            existing_categories=existing_categories,
        )
        llm = self.vision_llm or self.llm
        try:
            extracted = llm.structured_call(
                tool_name="extract_note",
                tool_description="把图片内容加工成结构化的知识笔记。",
                input_schema=self._extract_schema,
                user_prompt=user_prompt,
                system=self._extract_system,
                images=[img_data],
            )
        except Exception as e:
            logger.exception("LLM image extract failed for %s", source_path)
            return {}, ProcessResult(source_path, False, error=f"LLM failed: {e}")
        return extracted, None

    def _claim(self, source_path: Path) -> tuple[Any, ProcessResult | None]:
        """Claim file for processing. Returns (post, error_or_none)."""
        try:
            claimed, post = self.store.claim_for_processing(source_path)
        except Exception as e:
            return None, ProcessResult(source_path, False, error=f"read failed: {e}")
        if not claimed:
            logger.info("  skip: already %s", post.get("status") if post else "?")
            return None, ProcessResult(
                source_path, False,
                skipped_reason=f"already {post.get('status') if post else 'claimed'}",
            )
        return post, None

    def _check_duplicate(self, url: str, post: Any, source_path: Path) -> ProcessResult | None:
        """Check for duplicate source_url. Returns error ProcessResult or None."""
        if not url:
            return None
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
        return None

    def _fetch_if_needed(
        self, url: str, content: str, post: Any, source_path: Path,
    ) -> tuple[str, ProcessResult | None]:
        """Fetch URL content if needed. Returns (content, error_or_none)."""
        if not url or content:
            return content, None
        fr = self.fetcher.fetch(url)
        if not fr.ok:
            post["status"] = fr.status
            post["fetch_error"] = fr.error or ""
            post["fetch_at"] = now_iso()
            self.store.write_note(source_path, post)
            return "", ProcessResult(
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
        return content, None

    def _extract(self, content: str, post: Any, source_path: Path) -> tuple[dict, ProcessResult | None]:
        """Extract structured data via LLM. Returns (extracted, error_or_none)."""
        extra_meta = {k: v for k, v in post.metadata.items()
                      if k not in STANDARD_SOURCE_FIELDS}
        existing_categories = [
            c for c in self.store.existing_categories()
            if c in self._valid_categories
        ]
        user_prompt = self._build_extract_prompt(
            title_hint=post.get("title") or "",
            url=post.get("source") or "",
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
            return {}, ProcessResult(source_path, False, error=f"LLM failed: {e}")
        return extracted, None

    def _validate(self, extracted: dict, conf: float, post: Any, source_path: Path) -> ProcessResult | None:
        """Validate confidence and category. Returns error ProcessResult or None."""
        if conf < self.cfg.executor.classify_min_confidence:
            post["status"] = "skipped"
            post["skip_reason"] = f"low confidence: {conf}"
            post["llm_draft"] = extracted
            self.store.write_note(source_path, post)
            return ProcessResult(
                source_path, False,
                skipped_reason=f"low confidence {conf}",
            )

        cat = extracted.get("category", "")
        if cat not in self._valid_categories:
            logger.error("invalid category %r for %s", cat, source_path.name)
            return ProcessResult(
                source_path, False,
                error=f"invalid category: {cat}",
            )
        extracted["tags"] = sanitize_tags(extracted.get("tags", []))
        extracted["tags"] = [t for t in extracted["tags"] if t != cat]
        return None

    def _link_related(self, extracted: dict) -> str:
        """Find related notes and inject [[links]] into narrative."""
        related_links = self.store.find_related(extracted.get("related_keywords", []))
        narrative = extracted["narrative"]
        if related_links:
            narrative = narrative.rstrip() + "\n\n## 相关笔记\n\n" + "\n".join(
                f"- [[{wikilink_text(lk)}]]" for lk in related_links
            )
        return narrative

    def _write_topic(
        self, extracted: dict, conf: float, source_path: Path,
        url: str, extra_meta: dict, topic_body: str,
    ) -> Path:
        """Write topic note and return its path."""
        topic_meta = {
            "title": extracted["title"],
            "created": extracted.get("created") or now_iso(),
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
        return topic_path

    def _mark_processed(
        self, source_path: Path, post: Any, topic_path: Path, extracted: dict,
    ) -> None:
        """Update source file status to processed."""
        post["status"] = "processed"
        post["processed_at"] = now_iso()
        post["topic_ref"] = str(topic_path.relative_to(self.cfg.knowledge.root))
        post["tags"] = extracted["tags"]
        post["category"] = extracted["category"]
        self.store.write_note(source_path, post)

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

    def _build_image_extract_prompt(
        self,
        title_hint: str,
        caption: str,
        existing_categories: list[str],
    ) -> str:
        cats = "、".join(existing_categories) if existing_categories else "（暂无，请新建）"
        parts = [f"现有目录：{cats}"]
        if title_hint:
            parts.insert(0, f"原标题：{title_hint}")
        if caption:
            parts.append(f"附带说明：{caption}")
        parts.append("\n请根据图片内容进行笔记提取。")
        return "\n".join(parts)

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
