"""Writer: interactive writing mode with draft persistence."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .config import Config
from .llm import LLMClient
from .notes import (
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

# --------------- stages ---------------

STAGE_CONCEPT = "concept"
STAGE_FRAMEWORK = "framework"
STAGE_CONTENT = "content"
STAGE_REVIEW = "review"

# --------------- prompts ---------------

CONCEPT_SYSTEM = """\
你是一位写作助手。用户会给你一个写作想法，你需要结合提供的存量笔记内容，生成一段核心概念（约100字）。

核心概念必须包含三个要素：
1. 主题：这篇文章讲什么
2. 核心主张：这篇文章认为什么（必须有明确立场）
3. 预期读者：写给谁看

没有立场的文章没有写的必要。如果用户的想法本身缺乏立场，你应该基于存量内容推断一个可能的立场，供用户确认或修改。
"""

CONCEPT_TOOL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "topic": {
            "type": "string",
            "description": "主题：这篇文章讲什么（一句话）",
        },
        "thesis": {
            "type": "string",
            "description": "核心主张：这篇文章认为什么（一句话，有明确立场）",
        },
        "audience": {
            "type": "string",
            "description": "预期读者：写给谁看（一句话）",
        },
        "concept_text": {
            "type": "string",
            "description": "完整的核心概念（约100字，融合以上三要素的连贯文本）",
        },
    },
    "required": ["topic", "thesis", "audience", "concept_text"],
}

FRAMEWORK_SYSTEM = """\
你是一位写作助手。用户已确认了核心概念，现在需要你提出 2-3 个不同的文章框架方案。

每个框架方案包含：
- 方案名称（一个短语概括结构特点）
- 大纲（各段/节标题 + 一句话描述该段要点）

不同方案应在结构、论证路径、切入角度上有实质差异，而非仅仅重新排列段落顺序。
"""

FRAMEWORK_TOOL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "frameworks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "方案名称"},
                    "outline": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "heading": {"type": "string"},
                                "point": {"type": "string"},
                            },
                            "required": ["heading", "point"],
                        },
                        "description": "各段大纲",
                    },
                },
                "required": ["name", "outline"],
            },
            "description": "2-3 个框架方案",
        },
    },
    "required": ["frameworks"],
}

CONTENT_SYSTEM = """\
你是一位写作助手。用户已确认了核心概念和文章框架，现在需要你延展为完整内容。

要求：
1. 严格按照框架大纲的结构展开，使用 Markdown 格式
2. 内容要有实质性的论证和事实支撑，不要空洞
3. 保持核心主张的一致性
4. 行文连贯，段落之间有逻辑衔接

输出完正文后，你必须附上一份「自检清单」，主动标记以下问题：
- 数据/事实可能过时（标注来源年份）
- 因果推断缺乏直接证据（标注为你的推理）
- 与存量笔记中已有观点矛盾（指出矛盾点）
- 论证依赖的隐含前提假设（说明假设内容）

自检清单用 Markdown 列表格式，放在正文之后，用 `---` 分隔。
"""

DISCUSS_SYSTEM = """\
你是一位写作助手，正在与用户讨论文章内容。

核心原则：
1. 不迎合。如果用户的质疑缺乏依据，你应该礼貌但明确地指出
2. 如果你认为用户是对的，直接承认并说明如何修改
3. 引用存量笔记和搜索结果作为论据，不要凭空论证
4. 讨论结束后，输出修改后的完整正文（不是 diff，是全文）
5. 同时更新自检清单

用户可能：
- 对某个段落提出具体质疑
- 要求补充或删减内容
- 对自检清单中的项目做出回应
- 提出新的论点或角度

你应该就事论事地回应，然后给出修改后的全文。
"""

BACKFILL_SYSTEM = """\
你是一位知识管理助手。请评估这篇文章是否产生了值得回填到知识库的新知识。

回填的硬规则（必须严格遵守，只有符合条件才回填）：
1. 文章中引用了存量 topics 里没有的事实、数据或来源
2. 文章对已有 topic 提出了明确不同的结论

不符合以上任一条件，则不回填。不要因为"相关"或"有价值"就回填，只有真正的新增信息才有资格。
"""

BACKFILL_TOOL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "should_backfill": {
            "type": "boolean",
            "description": "是否需要回填",
        },
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["create", "update"],
                        "description": "新建 topic 还是更新已有 topic",
                    },
                    "topic_title": {
                        "type": "string",
                        "description": "目标 topic 标题（更新时为已有标题，新建时为建议标题）",
                    },
                    "reason": {
                        "type": "string",
                        "description": "回填理由：具体说明是什么新事实/数据/结论",
                    },
                    "content": {
                        "type": "string",
                        "description": "要回填的内容（Markdown 片段）",
                    },
                },
                "required": ["action", "topic_title", "reason", "content"],
            },
            "description": "需要回填的条目列表（should_backfill=false 时为空数组）",
        },
    },
    "required": ["should_backfill", "items"],
}


class Writer:
    """Interactive writing state machine with draft persistence."""

    DRAFT_NAME = "draft.md"

    def __init__(self, cfg: Config, llm: LLMClient):
        self.cfg = cfg
        self.llm = llm
        self.draft_path = cfg.knowledge.publish_path / self.DRAFT_NAME
        # In-memory discussion history (lost on restart; that's fine)
        self._history: list[dict[str, str]] = []

    # --------------- public API ---------------

    @property
    def active(self) -> bool:
        """Is there an active draft?"""
        return self.draft_path.exists()

    @property
    def stage(self) -> str | None:
        if not self.active:
            return None
        post = self._load_draft()
        return post.get("stage")

    def start(self, idea: str) -> str:
        """Begin a new writing session. Returns concept for user review."""
        logger.info("starting writing session, idea=%r", idea[:50])
        if self.active:
            return "已有一篇草稿正在进行中。请先 /publish 完成或手动删除 draft.md 再开始新的写作。"

        # Search existing topics for context
        topic_context = self._search_topics_for_context(idea)
        logger.debug("topic context hits: %d chars", len(topic_context))

        prompt = f"用户的写作想法：\n{idea}"
        if topic_context:
            prompt += f"\n\n以下是知识库中可能相关的存量笔记：\n{topic_context}"

        result = self.llm.structured_call(
            tool_name="generate_concept",
            tool_description="基于用户想法生成核心概念",
            input_schema=CONCEPT_TOOL_SCHEMA,
            user_prompt=prompt,
            system=CONCEPT_SYSTEM,
        )

        # Create draft
        concept_text = (
            f"**主题**：{result['topic']}\n\n"
            f"**核心主张**：{result['thesis']}\n\n"
            f"**预期读者**：{result['audience']}\n\n"
            f"{result['concept_text']}"
        )
        post = new_post(
            f"## 核心概念\n\n{concept_text}\n",
            title=result["topic"],
            stage=STAGE_CONCEPT,
            created=now_iso(),
            updated=now_iso(),
        )
        self._save_draft(post)
        self._history.clear()

        return (
            f"核心概念草案：\n\n"
            f"主题：{result['topic']}\n"
            f"核心主张：{result['thesis']}\n"
            f"预期读者：{result['audience']}\n\n"
            f"{result['concept_text']}\n\n"
            f"---\n"
            f"请确认、修改、或提出全新的核心概念。确认后我会提出框架方案。"
        )

    def handle_message(self, text: str) -> str:
        """Route message based on current stage."""
        stage = self.stage
        if stage is None:
            return "当前没有进行中的写作。请用 /write <想法> 开始。"

        if stage == STAGE_CONCEPT:
            return self._advance_to_framework(text)
        elif stage == STAGE_FRAMEWORK:
            return self._advance_to_content(text)
        elif stage in (STAGE_CONTENT, STAGE_REVIEW):
            return self._discuss(text)
        else:
            return f"未知状态：{stage}"

    def publish(self) -> str:
        """Finalize: write to 99-publish/, evaluate backfill, delete draft."""
        logger.info("publishing")
        if not self.active:
            return "当前没有进行中的写作。"

        post = self._load_draft()
        stage = post.get("stage")
        if stage not in (STAGE_CONTENT, STAGE_REVIEW):
            return f"当前阶段是 {stage}，还不能发布。请至少完成内容延展阶段。"

        # Extract sections from draft
        body = post.content
        title = post.get("title", "untitled")

        # Split off self-check list if present
        content_text, checklist = self._split_checklist(body)

        # Build published note
        pub_meta = {
            "title": title,
            "created": post.get("created", now_iso()),
            "published_at": now_iso(),
            "tags": sanitize_tags(post.get("tags") or []),
            "status": "published",
        }
        pub_post = new_post(content_text.strip() + "\n", **pub_meta)

        stem = slugify(title)
        pub_path = unique_path(self.cfg.knowledge.publish_path, stem)
        write_note(pub_path, pub_post)
        logger.info("published title=%r path=%s", title, pub_path)

        # Evaluate backfill
        backfill_msg = self._evaluate_backfill(title, content_text)
        logger.info("backfill result: %s", backfill_msg[:100] if backfill_msg else "none")

        # Clean up
        self._delete_draft()
        self._history.clear()

        rel = pub_path.relative_to(self.cfg.knowledge.root)
        result = f"已发布到 {rel}"
        if backfill_msg:
            result += f"\n\n{backfill_msg}"
        return result

    # --------------- stage transitions ---------------

    def _advance_to_framework(self, feedback: str) -> str:
        """User confirmed/modified concept → generate frameworks."""
        logger.info("advancing to framework stage")
        post = self._load_draft()

        # Update concept section if user provided modifications
        concept_section = self._extract_section(post.content, "核心概念")
        topic_context = self._search_topics_for_context(concept_section)

        prompt = (
            f"已确认的核心概念：\n{concept_section}\n\n"
            f"用户反馈：\n{feedback}"
        )
        if topic_context:
            prompt += f"\n\n存量笔记参考：\n{topic_context}"

        result = self.llm.structured_call(
            tool_name="generate_frameworks",
            tool_description="基于核心概念生成2-3个框架方案",
            input_schema=FRAMEWORK_TOOL_SCHEMA,
            user_prompt=prompt,
            system=FRAMEWORK_SYSTEM,
        )

        # Format frameworks for display and storage
        frameworks = result["frameworks"]
        logger.info("frameworks generated: %d", len(frameworks))
        display_parts = []
        storage_parts = []
        for i, fw in enumerate(frameworks, 1):
            display_parts.append(f"方案 {i}：{fw['name']}")
            storage_parts.append(f"### 方案 {i}：{fw['name']}")
            for item in fw["outline"]:
                display_parts.append(f"  - {item['heading']}：{item['point']}")
                storage_parts.append(f"- **{item['heading']}**：{item['point']}")
            display_parts.append("")
            storage_parts.append("")

        # Update draft
        post.content = (
            self._extract_section(post.content, "核心概念", keep_header=True)
            + "\n\n## 框架\n\n"
            + "\n".join(storage_parts)
        )
        post["stage"] = STAGE_FRAMEWORK
        post["updated"] = now_iso()
        self._save_draft(post)

        return (
            "以下是 2-3 个框架方案：\n\n"
            + "\n".join(display_parts)
            + "---\n"
            "请选择一个方案（如「选方案1」），在此基础上修改，或提出全新框架。"
        )

    def _advance_to_content(self, feedback: str) -> str:
        """User chose/modified framework → generate full content."""
        logger.info("advancing to content stage")
        post = self._load_draft()

        concept_section = self._extract_section(post.content, "核心概念")
        framework_section = self._extract_section(post.content, "框架")
        topic_context = self._search_topics_for_context(concept_section)

        prompt = (
            f"核心概念：\n{concept_section}\n\n"
            f"可选框架：\n{framework_section}\n\n"
            f"用户选择/反馈：\n{feedback}"
        )
        if topic_context:
            prompt += f"\n\n存量笔记参考：\n{topic_context}"

        content = self.llm.text_call(
            user_prompt=prompt,
            system=CONTENT_SYSTEM,
        )
        logger.info("content generated, length=%d", len(content))

        # Update draft
        content_body, checklist = self._split_checklist(content)
        post.content = (
            self._extract_section(post.content, "核心概念", keep_header=True)
            + "\n\n"
            + self._extract_section(post.content, "框架", keep_header=True)
            + "\n\n## 正文\n\n"
            + content_body.strip()
            + "\n"
        )
        if checklist:
            post.content += f"\n## 自检清单\n\n{checklist.strip()}\n"

        post["stage"] = STAGE_CONTENT
        post["updated"] = now_iso()
        self._save_draft(post)

        # Init discussion history
        self._history = [
            {"role": "assistant", "content": content},
        ]

        return (
            content
            + "\n\n---\n"
            "请逐段审读。可以对任何内容提出质疑、修改意见，或对自检清单做出回应。"
            "满意后发送 /publish 完成发布。"
        )

    def _discuss(self, feedback: str) -> str:
        """Discussion round during content/review stage."""
        logger.info("discussion round, history_len=%d", len(self._history))
        post = self._load_draft()

        concept_section = self._extract_section(post.content, "核心概念")
        current_content = self._extract_section(post.content, "正文")
        current_checklist = self._extract_section(post.content, "自检清单")
        topic_context = self._search_topics_for_context(feedback)

        # Build conversation with history
        messages = [
            {
                "role": "user",
                "content": (
                    f"核心概念：\n{concept_section}\n\n"
                    f"当前正文：\n{current_content}\n\n"
                    f"当前自检清单：\n{current_checklist}"
                ),
            },
            {"role": "assistant", "content": "好的，我已了解当前文章内容。请提出你的意见。"},
        ]
        # Append discussion history
        messages.extend(self._history)
        # Add current feedback
        user_msg = feedback
        if topic_context:
            user_msg += f"\n\n[系统补充的存量笔记参考：\n{topic_context}]"
        messages.append({"role": "user", "content": user_msg})

        response = self.llm.text_call(
            system=DISCUSS_SYSTEM,
            messages=messages,
        )

        # Track history
        self._history.append({"role": "user", "content": feedback})
        self._history.append({"role": "assistant", "content": response})

        # Try to extract updated content from response and update draft
        draft_updated = "## " in response or "# " in response
        logger.debug("draft updated from response: %s", draft_updated)
        if draft_updated:
            content_body, checklist = self._split_checklist(response)
            post.content = (
                self._extract_section(post.content, "核心概念", keep_header=True)
                + "\n\n"
                + self._extract_section(post.content, "框架", keep_header=True)
                + "\n\n## 正文\n\n"
                + content_body.strip()
                + "\n"
            )
            if checklist:
                post.content += f"\n## 自检清单\n\n{checklist.strip()}\n"

        post["stage"] = STAGE_REVIEW
        post["updated"] = now_iso()
        self._save_draft(post)

        return response

    # --------------- backfill ---------------

    def _evaluate_backfill(self, title: str, content: str) -> str:
        """Evaluate whether the article produces new knowledge to backfill."""
        logger.info("evaluating backfill for %r", title)
        topic_context = self._search_topics_for_context(title, max_notes=20)
        if not topic_context:
            return ""

        prompt = (
            f"文章标题：{title}\n\n"
            f"文章内容：\n{content}\n\n"
            f"以下是知识库中已有的相关笔记：\n{topic_context}"
        )

        try:
            result = self.llm.structured_call(
                tool_name="evaluate_backfill",
                tool_description="评估文章是否产生了需要回填知识库的新知识",
                input_schema=BACKFILL_TOOL_SCHEMA,
                user_prompt=prompt,
                system=BACKFILL_SYSTEM,
            )
        except Exception as e:
            logger.warning("backfill evaluation failed: %s", e)
            return ""

        if not result.get("should_backfill") or not result.get("items"):
            logger.debug("backfill: nothing to backfill")
            return ""

        # Execute backfill
        items = result["items"]
        logger.info("backfill: %d items to process", len(items))
        backfill_lines = ["回填到知识库："]
        for item in items:
            action = item["action"]
            topic_title = item["topic_title"]
            reason = item["reason"]

            if action == "create":
                self._backfill_create(topic_title, item["content"], title)
                backfill_lines.append(f"  + 新建 topic：{topic_title}（{reason}）")
            elif action == "update":
                updated = self._backfill_update(topic_title, item["content"], title)
                if updated:
                    backfill_lines.append(f"  ~ 更新 topic：{topic_title}（{reason}）")
                else:
                    backfill_lines.append(f"  ? 未找到 topic：{topic_title}，跳过更新")

        return "\n".join(backfill_lines)

    def _backfill_create(self, topic_title: str, content: str, source_title: str) -> Path:
        """Create a new topic note from backfill."""
        logger.info("backfill_create topic=%r", topic_title)
        meta = {
            "title": topic_title,
            "created": now_iso(),
            "backfilled_from": source_title,
            "status": "active",
        }
        post = new_post(content.strip() + "\n", **meta)
        # Put in a general category dir; could be smarter later
        topic_dir = self.cfg.knowledge.topics_path
        stem = slugify(topic_title)
        path = unique_path(topic_dir, stem)
        write_note(path, post)
        logger.info("backfill_create path=%s", path)
        return path

    def _backfill_update(self, topic_title: str, content: str, source_title: str) -> bool:
        """Append content to an existing topic note. Returns True if found."""
        logger.info("backfill_update topic=%r", topic_title)
        topics_root = self.cfg.knowledge.topics_path
        if not topics_root.exists():
            return False

        # Find by title match
        for md in topics_root.rglob("*.md"):
            try:
                post = read_note(md)
            except Exception:
                continue
            if post.get("title") == topic_title or md.stem == slugify(topic_title):
                # Append
                logger.info("backfill_update found topic=%r at %s", topic_title, md)
                post.content = (
                    post.content.rstrip()
                    + f"\n\n## 来自《{source_title}》的补充\n\n"
                    + content.strip()
                    + "\n"
                )
                post["updated"] = now_iso()
                write_note(md, post)
                return True
        logger.debug("backfill_update topic=%r not found", topic_title)
        return False

    # --------------- helpers ---------------

    def _load_draft(self):
        return read_note(self.draft_path)

    def _save_draft(self, post) -> None:
        write_note(self.draft_path, post)

    def _delete_draft(self) -> None:
        if self.draft_path.exists():
            self.draft_path.unlink()

    def _search_topics_for_context(self, query: str, max_notes: int = 5) -> str:
        """Search topics using category/tag structured filtering + keyword matching."""
        topics_root = self.cfg.knowledge.topics_path
        if not topics_root.exists():
            return ""

        query_lower = query.lower()
        words = [w for w in query_lower.split() if len(w) >= 2]
        logger.debug("search_topics query_words=%d words=%r", len(words), words[:5])
        if not words:
            return ""

        hits: list[tuple[float, str, str]] = []
        for md in topics_root.rglob("*.md"):
            try:
                post = read_note(md)
            except Exception:
                continue

            title = post.get("title") or md.stem
            category = (post.get("category") or "").lower()
            tags = [t.lower() for t in (post.get("tags") or [])]

            # Layer 1: structured match (category + tags)
            struct_score = 0.0
            for w in words:
                if w in category:
                    struct_score += 3.0
                for tag in tags:
                    if w in tag:
                        struct_score += 2.0
                        break  # one match per word per note

            # Layer 2: keyword match on title + content
            title_lower = title.lower()
            content_lower = post.content[:500].lower()
            keyword_score = 0.0
            for w in words:
                if w in title_lower:
                    keyword_score += 2.0
                elif w in content_lower:
                    keyword_score += 1.0

            total = struct_score + keyword_score
            if total > 0:
                summary = post.content[:200].strip()
                hits.append((total, title, summary))

        hits.sort(key=lambda x: -x[0])
        logger.debug("search_topics scanned files, hits=%d", len(hits))
        hits = hits[:max_notes]

        if not hits:
            return ""

        parts = []
        for _, title, summary in hits:
            parts.append(f"### {title}\n{summary}\n")
        return "\n".join(parts)

    @staticmethod
    def _extract_section(body: str, heading: str, keep_header: bool = False) -> str:
        """Extract content under a ## heading from markdown body."""
        lines = body.split("\n")
        start = None
        end = None
        for i, line in enumerate(lines):
            if line.strip().startswith(f"## {heading}"):
                start = i
            elif start is not None and line.strip().startswith("## ") and i > start:
                end = i
                break
        if start is None:
            return ""
        section_lines = lines[start:end] if end else lines[start:]
        if not keep_header and section_lines:
            section_lines = section_lines[1:]  # skip the ## heading line
        return "\n".join(section_lines).strip()

    @staticmethod
    def _split_checklist(text: str) -> tuple[str, str]:
        """Split content into (main_body, checklist) at --- separator."""
        # Look for --- near the end that separates checklist
        parts = text.rsplit("\n---\n", 1)
        if len(parts) == 2:
            return parts[0], parts[1]
        # Also try ## 自检清单 heading
        if "## 自检清单" in text:
            idx = text.index("## 自检清单")
            return text[:idx].rstrip(), text[idx + len("## 自检清单"):].strip()
        return text, ""
