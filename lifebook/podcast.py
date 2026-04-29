"""Podcast generator: topic note -> script -> audio."""
from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass
from pathlib import Path

from .audio import AudioProcessor
from .config import Config
from .llm import LLMClient
from .notes import read_note
from .tts import TTSClient, TTSError

logger = logging.getLogger(__name__)

_PODCAST_SKIP_SECTIONS = {"## 相关笔记", "## 来源"}
_CHARS_PER_MINUTE = 180
_TTS_FAILURE_THRESHOLD = 0.5


def _extract_podcast_content(raw_content: str) -> str:
    """Extract high-value sections for podcast, stop at first skip section."""
    lines = raw_content.strip().splitlines()
    result: list[str] = []
    for line in lines:
        if line.strip() in _PODCAST_SKIP_SECTIONS:
            break
        result.append(line)
    return "\n".join(result).strip()


def truncate_at_boundary(text: str, max_chars: int = 5000) -> str:
    """Truncate text at a paragraph boundary instead of hard character limit.

    Falls back to hard truncation if no paragraph boundary is found within range.
    """
    if len(text) <= max_chars:
        return text

    # Find the last paragraph break before max_chars
    truncated = text[:max_chars]
    last_newline = truncated.rfind("\n\n")
    if last_newline > max_chars * 0.5:
        return truncated[:last_newline].rstrip()

    # Fallback: try single newline
    last_single = truncated.rfind("\n")
    if last_single > max_chars * 0.5:
        return truncated[:last_single].rstrip()

    # Hard fallback
    return truncated.rstrip()


def select_notes(
    topics_path: Path, since: datetime.date, limit: int = 10
) -> tuple[list[Path], int]:
    """Select recent notes by frontmatter date, falling back to mtime.

    Uses ``processed_at`` or ``created`` from YAML frontmatter when available,
    falling back to filesystem modification time.

    Returns (selected_paths, total_matching_count).
    """
    candidates: list[tuple[float, Path]] = []
    for p in topics_path.rglob("*.md"):
        if p.name.startswith("."):
            continue
        date_val = _frontmatter_date(p)
        if date_val is not None:
            ts = date_val.timestamp()
        else:
            ts = p.stat().st_mtime
        if datetime.date.fromtimestamp(ts) >= since:
            candidates.append((ts, p))

    candidates.sort(key=lambda x: x[0], reverse=True)
    total = len(candidates)
    selected = [p for _, p in candidates[:limit]]
    return selected, total


def _frontmatter_date(p: Path) -> datetime.datetime | None:
    """Extract processed_at or created from frontmatter, return as datetime."""
    try:
        post = read_note(p)
    except (FileNotFoundError, UnicodeDecodeError, ValueError):
        return None

    for key in ("processed_at", "created"):
        val = post.get(key)
        if val is None:
            continue
        if isinstance(val, datetime.datetime):
            return val
        try:
            return datetime.datetime.fromisoformat(str(val))
        except ValueError:
            continue
    return None


_SCRIPT_BASE = (
    "你是一位叫 Mia 的播客节目主持人，你的听众叫大毛。\n"
    "这是单人独白，不是对话。禁止出现 A:、B:、甲:、乙: 或任何形式的对话格式。\n"
    "格式要求：每行一句口播稿，直接输出文字，不要加说话人前缀。\n"
    "风格要求：口语化、有节奏感、自然流畅，像在跟大毛聊天。偶尔称呼大毛来拉近距离。\n"
    "在适当的地方用括号加入语气或动作描述，例如：（偷笑）（认真）（停顿）（叹气）。\n"
    "不要每句都加，只在关键转折或情绪变化时使用。\n"
)

_SCRIPT_SYSTEM = (
    _SCRIPT_BASE
    + "根据提供的知识笔记内容，生成一段单人播客脚本。\n"
    + "开头要有简短的问候和引入，例如：早上好呀大毛，（精神满满）今天咱们来聊一个有意思的话题。\n"
    + "内容要求：覆盖笔记的核心要点，有引子、有展开、有总结。\n"
    + "涉及出口管制、地缘政治、军事、制裁等敏感话题时，用中性技术视角表述，聚焦产业影响和技术细节，避免情绪化用词。\n"
    + "段落之间加入（短暂停顿，轻轻吸气）作为自然过渡，但不要在开头问候后使用。\n"
    + "结尾用 Mia 的身份告别，例如：好了大毛，今天就聊到这里，我是 Mia，咱们下期见！\n"
    + "只输出脚本内容，不要加任何标题、说明或编号。"
)

_SCRIPT_SYSTEM_MULTI = (
    _SCRIPT_BASE
    + "根据提供的多篇知识笔记内容，生成一段单人播客脚本。\n"
    + "目标时长约 30 分钟（约 5000 字口播稿）。\n"
    + "如果内容丰富，可以适当展开细节和例子；如果笔记较少，可以深入分析每篇的核心观点。\n"
    + "开头要有简短的问候和引入，例如：早上好呀大毛，（精神满满）今天咱们来聊聊最近发生的几件有意思的事。\n"
    + "内容要求：覆盖每篇笔记的核心要点，话题之间自然过渡，有引子、有展开、有总结。\n"
    + "涉及出口管制、地缘政治、军事、制裁等敏感话题时，用中性技术视角表述，聚焦产业影响和技术细节，避免情绪化用词。\n"
    + "每个新话题的第一句前加入（短暂停顿，轻轻吸气）作为自然过渡，但不要在开头问候后使用。\n"
    + "结尾用 Mia 的身份告别。\n"
    + "{has_more_hint}"
    + "只输出脚本内容，不要加任何标题、说明或编号。"
)


class PodcastGenerator:
    _PODCAST_MAX_TOKENS = 16384

    def __init__(
        self,
        cfg: Config,
        llm: LLMClient,
        tts: TTSClient | None = None,
        audio: AudioProcessor | None = None,
    ):
        self.cfg = cfg
        self.llm = llm
        self.tts = tts or TTSClient(cfg.tts)
        self.audio = audio or AudioProcessor()

    def generate_script(self, title: str, content: str) -> list[ScriptSegment]:
        """Generate podcast monologue script from note content."""
        prompt = f"标题：{title}\n\n{content}"
        raw = self.llm.text_call(user_prompt=prompt, system=_SCRIPT_SYSTEM)
        return _parse_segments(raw)

    def generate_multi_script(
        self, notes: list[Path], has_more: bool
    ) -> list[ScriptSegment]:
        """Generate a combined podcast script from multiple notes."""
        parts: list[str] = []
        for p in notes:
            try:
                post = read_note(p)
                title = post.get("title", p.stem)
                content = truncate_at_boundary(
                    _extract_podcast_content(post.content), max_chars=5000
                )
                parts.append(f"## {title}\n{content}")
            except (FileNotFoundError, UnicodeDecodeError, ValueError) as e:
                logger.warning("Skipping note %s: %s", p.name, e)
                continue

        if not parts:
            raise ValueError("No readable notes found")

        prompt = "\n\n".join(parts)
        has_more_hint = (
            "在结尾处自然地提到还有更多有趣的内容，建议大毛有空去知识库看看。\n"
            if has_more
            else ""
        )
        system = _SCRIPT_SYSTEM_MULTI.format(has_more_hint=has_more_hint)

        raw = self.llm.text_call(
            user_prompt=prompt, system=system,
            max_tokens=self._PODCAST_MAX_TOKENS,
        )
        script_chars = len(raw)
        logger.info(
            "Generated script: %d chars (~%.1f min)",
            script_chars, script_chars / _CHARS_PER_MINUTE,
        )
        return _parse_segments(raw)

    def synthesize_script(self, segments: list[ScriptSegment]) -> bytes:
        """Synthesize each segment independently, skip content-filtered ones, concat.

        Raises TTSError if more than 50% of segments fail synthesis.
        """
        parts: list[bytes] = []
        failures = 0
        for i, seg in enumerate(segments):
            try:
                audio = self.tts.synthesize(seg.text)
                parts.append(audio)
            except TTSError as e:
                logger.warning("Segment %d skipped: %s", i, e)
                failures += 1
                continue

        total = len(segments)
        if total > 0 and failures / total > _TTS_FAILURE_THRESHOLD:
            raise TTSError(
                f"TTS failure rate {failures}/{total} exceeds {_TTS_FAILURE_THRESHOLD:.0%} threshold"
            )

        if not parts:
            raise TTSError("All segments failed TTS synthesis")
        if len(parts) == 1:
            return parts[0]
        return self.audio.concat_audio(parts)

    def generate(self, note_path: Path) -> tuple[bytes, int]:
        """Full pipeline: note -> script -> TTS.

        Returns (audio_bytes, duration_seconds).
        """
        if not note_path.exists():
            raise FileNotFoundError(f"Note not found: {note_path}")

        post = read_note(note_path)
        title = post.get("title", note_path.stem)
        content = _extract_podcast_content(post.content)

        segments = self.generate_script(title, content)
        if not segments:
            raise ValueError("LLM produced no valid script segments")

        audio_bytes = self.synthesize_script(segments)
        duration = self.audio.get_duration(audio_bytes)
        return audio_bytes, duration

    def generate_multi(
        self, note_paths: list[Path], has_more: bool
    ) -> tuple[bytes, int]:
        """Full pipeline: multiple notes -> script -> TTS."""
        if not note_paths:
            raise ValueError("No notes provided")

        segments = self.generate_multi_script(note_paths, has_more)
        if not segments:
            raise ValueError("LLM produced no valid script segments")

        audio_bytes = self.synthesize_script(segments)
        duration = self.audio.get_duration(audio_bytes)
        return audio_bytes, duration


@dataclass
class ScriptSegment:
    speaker: str
    text: str


def _parse_segments(raw: str) -> list[ScriptSegment]:
    """Parse LLM output into script segments."""
    segments: list[ScriptSegment] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        segments.append(ScriptSegment(speaker="host", text=line))
    return segments
