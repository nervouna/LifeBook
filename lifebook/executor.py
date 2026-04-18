"""Executor: process inbox files into topic notes."""
from __future__ import annotations

import fcntl
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import Config
from .fetcher import Fetcher
from .llm import LLMClient
from .notes import (
    CN_TZ,
    new_post,
    now_iso,
    read_note,
    sanitize_tags,
    slugify,
    unique_path,
    wikilink_text,
    write_note,
)

logger = logging.getLogger(__name__)


EXTRACT_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {
            "type": "string",
            "description": "笔记标题，简洁、具体，不超过 40 字。",
        },
        "summary": {
            "type": "string",
            "description": "一句话概括这篇内容的核心主张或信息。",
        },
        "key_points": {
            "type": "array",
            "items": {"type": "string"},
            "description": "3-7 条结构化要点，每条一句话，覆盖原文主要信息。",
        },
        "narrative": {
            "type": "string",
            "description": "加工后的可读 Markdown 正文，段落连贯，保留原文关键事实和数据，可含小标题。",
        },
        "tags": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "2-4 个标签。必须遵守 Obsidian 标签语法：仅含中文/英文/数字/连字符"
                "（-）/下划线（_），禁止空格、点号、引号、括号、斜杠等任何其他标点。"
                "不带 # 号。至少包含一个内容性质类标签，从以下白名单中选：资讯、趣闻、"
                "教程、观点、深度分析、参考文档、工具介绍、案例研究。其余为主题标签，"
                "避免过于宽泛（如\"技术\"）。反例：\"Node.js SDK\"（含空格和点）应写作"
                "\"NodeJS-SDK\"；\"API调用\"合法。"
            ),
            "minItems": 2,
            "maxItems": 4,
        },
        "category": {
            "type": "string",
            "enum": [
                "AI技术",
                "开发者工具",
                "半导体",
                "消费电子",
                "媒体生态",
                "组织与劳动",
                "科技监管",
                "经济与产业",
                "3D打印与数字制造",
                "游戏",
                "生活方式",
            ],
            "description": (
                "归档目录名，必须严格从枚举值中选一个。唯一维度是**主题领域/行业/学科**。"
                "边界优先级（避免打架）："
                "(1) 游戏引擎/游戏中的 AI 技术 → AI技术，不归游戏；"
                "(2) CAD/建模库主线是'Python 库/SDK' → 开发者工具，主线是'3D 打印工作流/硬件/材料' → 3D打印与数字制造；"
                "(3) 硬件产品发布/技术/参数 → 消费电子；使用场景/选购/搭配/体验 → 生活方式；"
                "(4) 远程办公/职场转型等若主线是管理实践 → 组织与劳动，若主线是个人状态 → 生活方式；"
                "(5) 宏观产业分析/消费降级/平台经济 → 经济与产业；个人消费选择 → 生活方式；"
                "(6) AI 监管/平台监管/数据合规/未成年人保护 → 科技监管，不分散到具体领域；"
                "(7) 芯片设计/制造/封装/存储统一归 半导体（不再分'半导体制造'）。"
            ),
        },
        "category_is_new": {
            "type": "boolean",
            "description": "始终返回 false（category 已固定为枚举）。保留字段向后兼容。",
        },
        "related_keywords": {
            "type": "array",
            "items": {"type": "string"},
            "description": "3-8 个用于查找相关笔记的关键词（人名、技术名、概念名等）。",
        },
        "confidence": {
            "type": "number",
            "description": "0-1，表示你对分类和要点抽取的置信度。",
            "minimum": 0,
            "maximum": 1,
        },
    },
    "required": ["title", "summary", "key_points", "narrative", "tags", "category",
                 "category_is_new", "related_keywords", "confidence"],
}


EXTRACT_SYSTEM = """你是一位严谨的知识库编辑。你的任务是把一篇原始素材加工成结构化的主题笔记。

分类与标签的分野（重要）：
- category 固定为 11 选一的枚举：AI技术、开发者工具、半导体、消费电子、
  媒体生态、组织与劳动、科技监管、经济与产业、3D打印与数字制造、游戏、
  生活方式。必须严格从这个列表里选一个，不得新建、不得改名、不得合并。
- 边界优先级（遇到模糊主题时按此决策）：
  * 游戏引擎/游戏内的 AI 技术 → AI技术（不归游戏）
  * CAD/建模库主线是"Python 库/SDK/API" → 开发者工具；主线是"3D 打印
    工作流/打印机硬件/材料" → 3D打印与数字制造
  * 硬件产品发布/技术/参数 → 消费电子；使用场景/选购/体验/搭配 → 生活方式
  * 职场转型/远程办公：管理实践视角 → 组织与劳动；个人状态视角 → 生活方式
  * 宏观产业/消费降级/平台经济分析 → 经济与产业；个人消费选择 → 生活方式
  * AI 监管/平台监管/数据合规/未成年人保护 → 科技监管（不散到具体领域）
  * 芯片设计/制造/封装/存储 → 半导体（不再分"半导体制造"）
- tag 承担其余所有维度：内容性质（资讯/教程/趣闻等）、具体主体（人名/
  产品名/概念名）、交叉领域。一篇笔记可以有多个 tag。

要求：
1. 保留原文核心事实、数据、论点，不虚构。
2. narrative 必须是可读的中文 Markdown 正文，不是 JSON 或列表堆叠。
3. key_points 是对 narrative 的高密度提炼，用于后续检索和关联。
4. 如果原文语言是英文，narrative 用中文改写，但保留专有名词原文。
5. category 严格从枚举中选。category_is_new 始终返回 false。
6. tags 必须严格遵守 Obsidian 语法：仅含中文/英文/数字/连字符/下划线，
   禁止空格和任何标点。含空格或点号的词要改写（"Node.js SDK" → "NodeJS-SDK"）。
7. tags 中必须至少有一个内容性质类标签（资讯/趣闻/教程/观点/深度分析/
   参考文档/工具介绍/案例研究），方便按阅读场景过滤。
8. tags 不得与 category 同名（避免信息重复）。例如 category=AI技术 时，
   tag 里不要再出现"AI技术"，应选更具体的主体/交叉领域词。

文体硬性要求（narrative 正文必须遵守，违反任何一条都视为失败）：
A. 禁用 emoji 和装饰符号。标题和正文不得出现 ⚙️🧠🚀💡✅🔥✨📌🎯 等任何
   表情符号或装饰字符。
B. narrative 不得以 H1（# 标题）重复笔记 title。可直接从内容起笔，或使用
   H2（##）分节。
C. 禁用过渡句、铺垫句、总结收尾段。例如"以下是..."、"综上所述"、
   "总的来说"、"这套方案为...提供了完整路径"、"可根据具体场景灵活选择"
   等套话一律删除。
D. bold 仅用于关键数值或专有名词。同一段落内 **...** 最多出现 2 处。
E. narrative 必须承载 key_points 之外的新信息（机制、原理、适用场景、
   局限性、对比、来源背景等）。如果原文信息量不足以支撑正文新增内容，
   narrative 留空或极简，不要用话术凑字数重复 key_points。
F. 原文出现的具体数值、版本号、日期、百分比必须原样保留。禁止弱化为
   "约"、"通常"、"大致"、"可能"。原文是 40% 就写 40%，不要改成"约 40%"。
G. 列表项末尾不加句号。"名称：说明"格式使用全角冒号"："。
H. 所有引号一律使用直角引号「」（嵌套时外层「」内层『』）。禁止使用
   弯引号 " " ' '，也禁止使用直引号 " '。
I. 禁用无意义的连接词和套话：此外、另外、值得一提的是、需要注意的是、
   总的来说、综上、简而言之、不难看出、由此可见。需要衔接时直接陈述
   下一个事实。
J. 禁止使用破折号 — 或 ——。需要补充说明就另起一句，或用半角括号（）。"""


@dataclass
class ProcessResult:
    source_path: Path
    ok: bool
    topic_path: Path | None = None
    error: str | None = None
    skipped_reason: str | None = None


class Executor:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.llm = LLMClient(cfg.llm)
        self.fetcher = Fetcher(cfg.tavily, cfg.fetch)

    # ---------- public API ----------

    def recover_stale(self, timeout_minutes: int = 10, dry_run: bool = False) -> list[tuple[Path, str]]:
        """Roll back files stuck in `status: processing` for longer than timeout.

        Returns a list of (path, processing_at_string) for affected files.
        Typical cause: LLM returned empty tool_use 3 times, or process crashed
        between _claim_for_processing and terminal state write.
        """
        from datetime import datetime
        root = self.cfg.knowledge.sources_path
        if not root.exists():
            return []
        now = datetime.now(CN_TZ)
        stale: list[tuple[Path, str]] = []
        for p in sorted(root.glob("*.md")):
            try:
                post = read_note(p)
            except Exception as e:
                logger.warning("skip unreadable %s: %s", p, e)
                continue
            if post.get("status") != "processing":
                continue
            pa = post.get("processing_at")
            if not pa:
                # Missing timestamp = treat as stale (orphan)
                stale.append((p, "(no processing_at)"))
                if not dry_run:
                    post["status"] = "inbox"
                    post.metadata.pop("processing_at", None)
                    write_note(p, post)
                continue
            try:
                pa_dt = datetime.fromisoformat(pa)
            except Exception:
                stale.append((p, f"(bad timestamp: {pa})"))
                if not dry_run:
                    post["status"] = "inbox"
                    post.metadata.pop("processing_at", None)
                    write_note(p, post)
                continue
            age_min = (now - pa_dt).total_seconds() / 60
            if age_min >= timeout_minutes:
                stale.append((p, f"{pa} ({age_min:.1f}min old)"))
                if not dry_run:
                    post["status"] = "inbox"
                    post.metadata.pop("processing_at", None)
                    write_note(p, post)
        return stale

    def scan_inbox(self) -> list[Path]:
        """List all sources files with status: inbox."""
        root = self.cfg.knowledge.sources_path
        if not root.exists():
            return []
        out = []
        for p in sorted(root.glob("*.md")):
            try:
                post = read_note(p)
            except Exception as e:
                logger.warning("skip unreadable %s: %s", p, e)
                continue
            if post.get("status") == "inbox":
                out.append(p)
        return out

    def process_file(self, source_path: Path) -> ProcessResult:
        """Process a single source file end-to-end.

        File-level idempotency: we hold an exclusive flock on the source file
        just long enough to atomically flip `status: inbox → processing`. If
        another worker (another CLI invocation, the feishu bot, etc.) already
        claimed this file, we return a skipped result immediately. The flock
        is released before the slow fetch + LLM calls so unrelated files are
        not blocked.
        """
        logger.info("process: %s", source_path.name)
        try:
            claimed, post = self._claim_for_processing(source_path)
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
                # Mark as skipped/failed and return
                post["status"] = fr.status  # needs_clip / fetch_failed
                post["fetch_error"] = fr.error or ""
                post["fetch_at"] = now_iso()
                write_note(source_path, post)
                return ProcessResult(
                    source_path, False,
                    skipped_reason=f"{fr.status}: {fr.error}",
                )
            content = fr.content
            # Write fetched content back to source file so it's auditable
            post.content = content
            if fr.title and not post.get("title"):
                post["title"] = fr.title
            post["fetch_via"] = fr.via
            post["fetched_at"] = now_iso()
            write_note(source_path, post)

        if not content:
            return ProcessResult(source_path, False, error="no content to process")

        # 2. Ask LLM to extract
        existing_categories = self._existing_categories()
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

        # 3. Low confidence → skipped
        conf = float(extracted.get("confidence", 0))
        if conf < self.cfg.executor.classify_min_confidence:
            post["status"] = "skipped"
            post["skip_reason"] = f"low confidence: {conf}"
            post["llm_draft"] = extracted  # keep for debugging
            write_note(source_path, post)
            return ProcessResult(
                source_path, False,
                skipped_reason=f"low confidence {conf}",
            )

        # 3.5. Sanitize tags to comply with Obsidian syntax. LLM sometimes emits
        # tags with spaces/dots (e.g. "Node.js SDK") which trigger Obsidian's
        # "invalid tag name" warnings. Always scrub before writing.
        extracted["tags"] = sanitize_tags(extracted.get("tags", []))
        # Also drop any tag that duplicates the category — they add no info and
        # the prompt already forbids this, but LLM output is not 100% reliable.
        cat = extracted.get("category", "")
        if cat:
            extracted["tags"] = [t for t in extracted["tags"] if t != cat]

        # Log when a new category is being created so review is easy later.
        if extracted.get("category_is_new") and (
            extracted.get("category") not in existing_categories
        ):
            logger.info(
                "  new category: %s (source=%s)",
                extracted["category"], source_path.name,
            )

        # 4. Find related topic notes and inject [[links]]
        related_links = self._find_related(extracted.get("related_keywords", []))
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
        # If slugify altered the title, expose the original as an alias so
        # [[original title]] wikilinks still resolve in Obsidian.
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

        logger.info("  → %s", topic_path.relative_to(self.cfg.knowledge.root))
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

    def _claim_for_processing(self, source_path: Path):
        """Atomically claim a source file: flip status inbox → processing.

        Returns (claimed: bool, post). If claimed=False, post reflects the
        current on-disk state (may be None on read error) and the caller
        should skip this file.

        Uses fcntl.flock on the source file itself to serialize racing workers.
        The lock is held only during the read-check-write cycle, not during
        the subsequent slow fetch/LLM work, so unrelated files run in parallel.
        """
        # Open for read+write so flock semantics are well-defined.
        with open(source_path, "r+", encoding="utf-8") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                fh.seek(0)
                post = read_note(source_path)
                if post.get("status") != "inbox":
                    return False, post
                post["status"] = "processing"
                post["processing_at"] = now_iso()
                write_note(source_path, post)
                return True, post
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)

    def _existing_categories(self) -> list[str]:
        root = self.cfg.knowledge.topics_path
        if not root.exists():
            return []
        return sorted([d.name for d in root.iterdir() if d.is_dir() and not d.name.startswith(".")])

    def _find_related(self, keywords: list[str], max_hits: int = 5) -> list[str]:
        """Scan topics/*/*.md; return titles whose title/tags/keywords match."""
        if not keywords:
            return []
        kw_lower = [k.lower() for k in keywords]
        hits: list[tuple[int, str]] = []
        root = self.cfg.knowledge.topics_path
        if not root.exists():
            return []
        for md in root.rglob("*.md"):
            try:
                post = read_note(md)
            except Exception:
                continue
            title = post.get("title") or md.stem
            haystack = " ".join([
                title,
                " ".join(post.get("tags") or []),
                " ".join(post.get("related_keywords") or []),
            ]).lower()
            score = sum(1 for k in kw_lower if k and k in haystack)
            if score > 0:
                hits.append((score, title))
        hits.sort(key=lambda x: (-x[0], x[1]))
        seen: set[str] = set()
        out: list[str] = []
        for _, t in hits:
            if t in seen:
                continue
            seen.add(t)
            out.append(t)
            if len(out) >= max_hits:
                break
        return out

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
        # Truncate very long content to protect token budget
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
