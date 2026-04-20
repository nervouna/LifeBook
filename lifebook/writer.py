"""Writer: interactive writing mode with draft persistence."""
from __future__ import annotations

import json
import logging
import shutil
import threading
from pathlib import Path

from .config import Config
from .llm import LLMClient
from .fetcher import WEB_SEARCH_TOOL, web_search
from .notes import (
    new_post,
    now_iso,
    sanitize_tags,
    slugify,
    unique_path,
    write_note,
)
from .prompts import (
    BACKFILL_SYSTEM,
    BACKFILL_TOOL_SCHEMA,
    CHECKLIST_SYSTEM,
    CONCEPT_SYSTEM,
    CONCEPT_TOOL_SCHEMA,
    CONTENT_SYSTEM,
    DISCUSS_SYSTEM,
    FRAMEWORK_SYSTEM,
    FRAMEWORK_TOOL_SCHEMA,
    SECTION_SYSTEM,
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
    """Interactive writing state machine with draft persistence.

    File structure:
    - draft.json: metadata (stage, concept, frameworks, checklist, etc.)
    - draft.md: pure article content (no frontmatter)
    - draft.history.json: discussion history
    """

    DRAFT_NAME = "draft.md"

    def __init__(self, cfg: Config, llm: LLMClient, store: NoteStore | None = None):
        self.cfg = cfg
        self.llm = llm
        self.store = store or NoteStore(cfg.knowledge)
        self.draft_path = cfg.knowledge.publish_path / self.DRAFT_NAME
        self.draft_meta_path = cfg.knowledge.publish_path / "draft.json"
        self.history_path = cfg.knowledge.publish_path / "draft.history.json"
        self._history: list[dict[str, str]] = []
        self._lock = threading.Lock()

    # --------------- public API ---------------

    @property
    def active(self) -> bool:
        """Is there an active draft?"""
        return self.draft_meta_path.exists()

    @property
    def stage(self) -> str | None:
        if not self.active:
            return None
        meta, _ = self._load_draft()
        return meta.get("stage") if meta else None

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

        # Create draft metadata
        meta = {
            "stage": STAGE_CONCEPT,
            "title": result["topic"],
            "created": now_iso(),
            "updated": now_iso(),
            "concept": {
                "topic": result["topic"],
                "thesis": result["thesis"],
                "audience": result["audience"],
                "concept_text": result["concept_text"],
            },
        }
        self._save_draft(meta, "")
        self._history.clear()
        # Also clear history file
        if self.history_path.exists():
            self.history_path.unlink()

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

    def publish(self, *, force: bool = False) -> str:
        """Finalize: write to 99-publish/, evaluate backfill, delete draft."""
        with self._lock:
            return self._publish(force=force)

    def _publish(self, *, force: bool = False) -> str:
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

        # Warn if checklist has items and force is not set
        if not force and checklist.strip():
            checklist_items = [
                line.strip()
                for line in checklist.strip().split("\n")
                if line.strip().startswith("- ")
            ]
            if checklist_items:
                items_text = "\n".join(checklist_items[:5])
                return (
                    f"自检清单中还有 {len(checklist_items)} 个未回应的项目：\n"
                    f"{items_text}\n\n"
                    f"请先回应清单中的问题，或发送 /publish --force 强制发布。"
                )

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
        meta, content = self._load_draft()

        concept = meta.get("concept", {}) if meta else {}
        concept_text = concept.get("concept_text", "")
        topic_context = self.store.search_topics_formatted(concept_text)

        prompt = f"已确认的核心概念：\n{concept_text}\n\n用户反馈：\n{feedback}"
        if topic_context:
            prompt += f"\n\n存量笔记参考：\n{topic_context}"

        result = self.llm.structured_call(
            tool_name="generate_frameworks",
            tool_description="基于核心概念生成2-3个框架方案",
            input_schema=FRAMEWORK_TOOL_SCHEMA,
            user_prompt=prompt,
            system=FRAMEWORK_SYSTEM,
        )

        frameworks = result["frameworks"]
        logger.info("frameworks generated: %d", len(frameworks))

        # Update metadata
        meta["stage"] = STAGE_FRAMEWORK
        meta["frameworks"] = frameworks
        meta["updated"] = now_iso()
        self._save_draft(meta, content)

        # Format for display
        display_parts = []
        for i, fw in enumerate(frameworks, 1):
            display_parts.append(f"方案 {i}：{fw['name']}")
            for item in fw["outline"]:
                display_parts.append(f"  - {item['heading']}：{item['point']}")
            display_parts.append("")

        return (
            "以下是 2-3 个框架方案：\n\n"
            + "\n".join(display_parts)
            + "---\n"
            "请选择一个方案（如「选方案1」），在此基础上修改，或提出全新框架。"
        )

    def _advance_to_content(self, feedback: str) -> str:
        """User chose/modified framework → generate content section by section."""
        logger.info("advancing to content stage (sequential)")
        meta, content = self._load_draft()

        concept = meta.get("concept", {}) if meta else {}
        concept_text = concept.get("concept_text", "")
        frameworks = meta.get("frameworks", [])
        topic_context = self.store.search_topics_formatted(concept_text)

        # Select framework by index or name
        outline = self._select_framework(frameworks, feedback)
        if not outline:
            return "未找到匹配的框架方案，请重新选择。"

        # Generate each section sequentially
        generated_sections: list[str] = []
        for item in outline:
            previous = "\n\n".join(generated_sections) if generated_sections else "（还没有已写好的章节）"
            prompt = (
                f"核心概念：\n{concept_text}\n\n"
                f"当前章节：{item['heading']}\n\n"
                f"章节要点：{item['point']}\n\n"
                f"之前已写好的章节：\n{previous}"
            )
            if topic_context:
                prompt += f"\n\n存量笔记参考：\n{topic_context}"
            section_content = self.llm.text_call(
                user_prompt=prompt,
                system=SECTION_SYSTEM,
            )
            generated_sections.append(section_content.strip())

        # Generate checklist separately
        full_body = "\n\n".join(generated_sections)
        checklist_prompt = f"文章正文：\n{full_body}"
        checklist_text = self.llm.text_call(
            user_prompt=checklist_prompt,
            system=CHECKLIST_SYSTEM,
        ).strip()

        # Update draft
        meta["stage"] = STAGE_CONTENT
        meta["checklist"] = checklist_text
        meta["updated"] = now_iso()
        self._save_draft(meta, full_body)

        # Init discussion history
        self._history = [
            {"role": "assistant", "content": full_body},
        ]

        return (
            full_body
            + "\n\n---\n"
            "请逐段审读。可以对任何内容提出质疑、修改意见，或对自检清单做出回应。"
            "满意后发送 /publish 完成发布。"
        )

    def _select_framework(self, frameworks: list[dict], feedback: str) -> list[dict] | None:
        """Select framework by index or name match from structured frameworks.

        Returns the outline list of the selected framework, or None if no match.
        """
        if not frameworks:
            return None

        fb = feedback.replace(" ", "")

        # Try matching by index: "方案1", "选方案2", etc.
        import re
        idx_match = re.search(r"方案(\d+)", fb)
        if idx_match:
            idx = int(idx_match.group(1)) - 1
            if 0 <= idx < len(frameworks):
                return frameworks[idx].get("outline", [])

        # Try matching by name
        for fw in frameworks:
            name = fw.get("name", "").replace(" ", "")
            if name and name in fb:
                return fw.get("outline", [])

        # Default to first framework
        return frameworks[0].get("outline", [])

    def _discuss(self, feedback: str) -> str:
        """Discussion round during content/review stage."""
        logger.info("discussion round, history_len=%d", len(self._history))
        meta, content = self._load_draft()

        concept = meta.get("concept", {}) if meta else {}
        concept_text = concept.get("concept_text", "")
        checklist = meta.get("checklist", "") if meta else ""
        topic_context = self.store.search_topics_formatted(feedback)

        # Load history from file
        self._load_history()

        # Build conversation with history
        messages = [
            {
                "role": "user",
                "content": (
                    f"核心概念：\n{concept_text}\n\n"
                    f"当前正文：\n{content}\n\n"
                    f"当前自检清单：\n{checklist}"
                ),
            },
            {"role": "assistant", "content": "好的，我已了解当前文章内容。请提出你的意见。"},
        ]
        messages.extend(self._history)
        user_msg = feedback
        if topic_context:
            user_msg += f"\n\n[系统补充的存量笔记参考：\n{topic_context}]"
        messages.append({"role": "user", "content": user_msg})

        # Closure to handle update_draft tool calls
        draft_updated = False

        def _handle_update_draft(inp: dict) -> str:
            nonlocal draft_updated
            new_content = inp["content"]
            new_checklist = inp.get("checklist", "")
            # Re-read draft to get latest state
            m, _ = self._load_draft()
            m["stage"] = STAGE_REVIEW
            m["updated"] = now_iso()
            if new_checklist:
                m["checklist"] = new_checklist
            self._save_draft(m, new_content)
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

        # Track and persist history
        self._history.append({"role": "user", "content": feedback})
        self._history.append({"role": "assistant", "content": response})

        # Cap history to prevent unbounded growth
        if len(self._history) > MAX_HISTORY:
            dropped = len(self._history) - MAX_HISTORY
            self._history = self._history[-MAX_HISTORY:]
            logger.info("history trimmed, dropped %d oldest entries", dropped)

        self._save_history()

        # If no tool call updated the draft, still mark as review stage
        if not draft_updated:
            meta["stage"] = STAGE_REVIEW
            meta["updated"] = now_iso()
            self._save_draft(meta, content)

        return response

    def _load_history(self) -> None:
        """Load discussion history from file."""
        if self.history_path.exists():
            with self.history_path.open("r", encoding="utf-8") as f:
                self._history = json.load(f)
        else:
            self._history = []

    def _save_history(self) -> None:
        """Save discussion history to file."""
        with self.history_path.open("w", encoding="utf-8") as f:
            json.dump(self._history, f, ensure_ascii=False, indent=2)

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
            return f"（回填评估失败：{e}）"

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
        self.store.write_note(path, post)
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

    def _load_draft(self) -> tuple[dict | None, str]:
        """Load draft from draft.json and draft.md.

        Returns (meta_dict, content_string). Returns (None, "") if no draft exists.
        """
        if not self.draft_meta_path.exists():
            return None, ""
        with self.draft_meta_path.open("r", encoding="utf-8") as f:
            meta = json.load(f)
        content = ""
        if self.draft_path.exists():
            content = self.draft_path.read_text(encoding="utf-8")
        return meta, content

    def _save_draft(self, meta: dict, content: str) -> None:
        """Save draft to draft.json and draft.md.

        Creates backup of both files before overwriting.
        """
        if self.draft_meta_path.exists():
            shutil.copy2(self.draft_meta_path, self.draft_meta_path.with_suffix(".json.bak"))
        if self.draft_path.exists():
            shutil.copy2(self.draft_path, self.draft_path.with_suffix(".md.bak"))

        self.draft_meta_path.parent.mkdir(parents=True, exist_ok=True)
        with self.draft_meta_path.open("w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        self.draft_path.write_text(content, encoding="utf-8")

    def _delete_draft(self) -> None:
        """Delete all draft files (json, md, history)."""
        for p in [self.draft_meta_path, self.draft_path, self.history_path]:
            p.unlink(missing_ok=True)

    def restore_draft(self) -> str:
        """Restore draft from backup. Returns status message."""
        with self._lock:
            bak_meta = self.draft_meta_path.with_suffix(".json.bak")
            if not bak_meta.exists():
                return "没有可恢复的备份。"
            shutil.copy2(bak_meta, self.draft_meta_path)
            bak_md = self.draft_path.with_suffix(".md.bak")
            if bak_md.exists():
                shutil.copy2(bak_md, self.draft_path)
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

    @staticmethod
    def _splice_unchanged(original: str, updated: str) -> str:
        """Replace [UNCHANGED] sections in updated with corresponding sections from original.

        When a ## section in updated contains only "[UNCHANGED]", the entire
        section content from original is substituted in.
        """
        import re
        if "[UNCHANGED]" not in updated:
            return updated

        # Parse both into heading→content maps
        def parse_sections(text: str) -> dict[str, str]:
            sections: dict[str, str] = {}
            current_key: str | None = None
            current_lines: list[str] = []
            in_code = False
            for line in text.split("\n"):
                stripped = line.strip()
                if stripped.startswith("```"):
                    in_code = not in_code
                if not in_code and re.match(r"^## .+", stripped):
                    if current_key is not None:
                        sections[current_key] = "\n".join(current_lines)
                    current_key = stripped
                    current_lines = [line]
                elif current_key is not None:
                    current_lines.append(line)
            if current_key is not None:
                sections[current_key] = "\n".join(current_lines)
            return sections

        orig_sections = parse_sections(original)
        upd_sections = parse_sections(updated)

        # Replace [UNCHANGED] sections
        for heading, content in upd_sections.items():
            if "[UNCHANGED]" in content and heading in orig_sections:
                upd_sections[heading] = orig_sections[heading]

        # Reassemble: keep order from updated
        result_parts: list[str] = []
        for heading in upd_sections:
            result_parts.append(upd_sections[heading])
        return "\n".join(result_parts)

    @staticmethod
    def _parse_outline(body: str, feedback: str) -> list[dict[str, str]]:
        """Parse framework body to extract outline items for the selected方案.

        Returns list of {"heading": ..., "point": ...} for the chosen方案.
        Defaults to first方案 if feedback doesn't match any.
        """
        import re

        # Split into scheme blocks: "### 方案 N：name\n- **h**：p\n..."
        scheme_re = re.compile(r"^### (方案\s*\d+)\s*[：:]\s*(.+)$")
        item_re = re.compile(r"^-\s+\*\*(.+?)\*\*\s*[：:]\s*(.+)$")

        schemes: list[tuple[str, str, list[dict[str, str]]]] = []
        current_name: str | None = None
        current_label: str | None = None
        current_items: list[dict[str, str]] = []

        for line in body.split("\n"):
            stripped = line.strip()
            m = scheme_re.match(stripped)
            if m:
                if current_label is not None:
                    schemes.append((current_label, current_name or "", current_items))
                current_label = m.group(1).replace(" ", "")
                current_name = m.group(2).strip()
                current_items = []
                continue
            m = item_re.match(stripped)
            if m and current_label is not None:
                current_items.append({"heading": m.group(1), "point": m.group(2)})

        if current_label is not None:
            schemes.append((current_label, current_name or "", current_items))

        if not schemes:
            return []

        # Match feedback to a scheme
        fb = feedback.replace(" ", "")
        for label, name, items in schemes:
            if label in fb or name in fb:
                return items
            # "选方案1" / "方案2" patterns
            num_match = re.search(r"方案(\d+)", label)
            if num_match and num_match.group(1) in fb:
                return items

        # Default to first
        return schemes[0][2]
