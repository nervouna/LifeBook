"""Writer: interactive writing mode with draft persistence."""
from __future__ import annotations

import logging
import threading
from pathlib import Path

from .config import Config
from .llm import LLMClient
from .fetcher import WEB_SEARCH_TOOL, web_search
from .notes import (
    new_post,
    now_iso,
    read_note,
    sanitize_tags,
    slugify,
    unique_path,
    write_note,
)
from .prompts import (
    BACKFILL_SYSTEM,
    BACKFILL_TOOL_SCHEMA,
    CONCEPT_SYSTEM,
    CONCEPT_TOOL_SCHEMA,
    CONTENT_SYSTEM,
    DISCUSS_SYSTEM,
    FRAMEWORK_SYSTEM,
    FRAMEWORK_TOOL_SCHEMA,
    UPDATE_DRAFT_TOOL,
)
from .store import NoteStore

logger = logging.getLogger(__name__)

# --------------- stages ---------------

STAGE_CONCEPT = "concept"
STAGE_FRAMEWORK = "framework"
STAGE_CONTENT = "content"
STAGE_REVIEW = "review"

MAX_HISTORY = 20  # max discussion turns (user+assistant pairs) kept in memory


class Writer:
    """Interactive writing state machine with draft persistence."""

    DRAFT_NAME = "draft.md"

    def __init__(self, cfg: Config, llm: LLMClient, store: NoteStore | None = None):
        self.cfg = cfg
        self.llm = llm
        self.store = store or NoteStore(cfg.knowledge)
        self.draft_path = cfg.knowledge.publish_path / self.DRAFT_NAME
        # In-memory discussion history (lost on restart; that's fine)
        self._history: list[dict[str, str]] = []
        self._lock = threading.Lock()

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
        with self._lock:
            return self._start(idea)

    def _start(self, idea: str) -> str:
        logger.info("starting writing session, idea=%r", idea[:50])
        if self.active:
            return "已有一篇草稿正在进行中。请先 /publish 完成或手动删除 draft.md 再开始新的写作。"

        # Search existing topics for context
        topic_context = self.store.search_topics_formatted(idea)
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
        with self._lock:
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
        with self._lock:
            return self._publish()

    def _publish(self) -> str:
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
        topic_context = self.store.search_topics_formatted(concept_section)

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
        topic_context = self.store.search_topics_formatted(concept_section)

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
        topic_context = self.store.search_topics_formatted(feedback)

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

        # Closure to handle update_draft tool calls
        draft_updated = False

        def _handle_update_draft(inp: dict) -> str:
            nonlocal draft_updated
            content_body = inp["content"]
            checklist = inp.get("checklist", "")
            # Re-read draft to get latest state
            p = self._load_draft()
            p.content = (
                self._extract_section(p.content, "核心概念", keep_header=True)
                + "\n\n"
                + self._extract_section(p.content, "框架", keep_header=True)
                + "\n\n## 正文\n\n"
                + content_body.strip()
                + "\n"
            )
            if checklist:
                p.content += f"\n## 自检清单\n\n{checklist.strip()}\n"
            p["stage"] = STAGE_REVIEW
            p["updated"] = now_iso()
            self._save_draft(p)
            draft_updated = True
            return "草稿已更新"

        response = self.llm.agentic_call(
            system=DISCUSS_SYSTEM,
            messages=messages,
            tools=[WEB_SEARCH_TOOL, UPDATE_DRAFT_TOOL],
            tool_executor={
                "web_search": lambda inp: web_search(inp["query"], self.cfg),
                "update_draft": _handle_update_draft,
            },
        )

        # Track history
        self._history.append({"role": "user", "content": feedback})
        self._history.append({"role": "assistant", "content": response})

        # Cap history to prevent unbounded growth
        if len(self._history) > MAX_HISTORY:
            dropped = len(self._history) - MAX_HISTORY
            self._history = self._history[-MAX_HISTORY:]
            logger.info("history trimmed, dropped %d oldest entries", dropped)

        # If no tool call updated the draft, still mark as review stage
        if not draft_updated:
            post = self._load_draft()
            post["stage"] = STAGE_REVIEW
            post["updated"] = now_iso()
            self._save_draft(post)

        return response

    # --------------- backfill ---------------

    def _evaluate_backfill(self, title: str, content: str) -> str:
        """Evaluate whether the article produces new knowledge to backfill."""
        logger.info("evaluating backfill for %r", title)
        topic_context = self.store.search_topics_formatted(title, max_notes=20)
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
        md = self.store.find_by_title(topic_title)
        if md is None:
            logger.debug("backfill_update topic=%r not found", topic_title)
            return False
        logger.info("backfill_update found topic=%r at %s", topic_title, md)
        post = self.store.read_note(md)
        post.content = (
            post.content.rstrip()
            + f"\n\n## 来自《{source_title}》的补充\n\n"
            + content.strip()
            + "\n"
        )
        post["updated"] = now_iso()
        self.store.write_note(md, post)
        return True

    # --------------- helpers ---------------

    DRAFT_BACKUP_NAME = "draft.bak.md"

    def _load_draft(self):
        return read_note(self.draft_path)

    @property
    def _backup_path(self) -> Path:
        return self.draft_path.with_suffix(".bak.md")

    def _save_draft(self, post) -> None:
        if self.draft_path.exists():
            import shutil
            shutil.copy2(self.draft_path, self._backup_path)
        write_note(self.draft_path, post)

    def _delete_draft(self) -> None:
        if self.draft_path.exists():
            self.draft_path.unlink()

    def restore_draft(self) -> str:
        """Restore draft from backup. Returns status message."""
        with self._lock:
            bak = self._backup_path
            if not bak.exists():
                return "没有可恢复的备份。"
            import shutil
            shutil.copy2(bak, self.draft_path)
            stage = self.stage or "unknown"
            logger.info("draft restored from backup, stage=%s", stage)
            return f"已恢复到上一版本（阶段：{stage}）"

    @staticmethod
    def _extract_section(body: str, heading: str, keep_header: bool = False) -> str:
        """Extract content under a ## heading from markdown body.

        Skips heading detection inside fenced code blocks (```).
        Only matches ## (H2) headings, not ### or deeper.
        """
        import re
        lines = body.split("\n")
        start = None
        end = None
        in_code_block = False
        heading_re = re.compile(rf"^## {re.escape(heading)}\s*$")
        any_h2_re = re.compile(r"^## .+")
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("```"):
                in_code_block = not in_code_block
                continue
            if in_code_block:
                continue
            if heading_re.match(stripped):
                start = i
            elif start is not None and any_h2_re.match(stripped) and i > start:
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
