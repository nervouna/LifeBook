"""Podcast generator: topic note → script → audio."""
from __future__ import annotations

import datetime
import logging
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import frontmatter

from .tts import TTSClient

logger = logging.getLogger(__name__)


def select_notes(
    topics_path: Path, since: datetime.date, limit: int = 10
) -> tuple[list[Path], int]:
    """Select recent notes by modification date.

    Returns (selected_paths, total_matching_count).
    """
    candidates: list[tuple[float, Path]] = []
    for p in topics_path.rglob("*.md"):
        if p.name.startswith("."):
            continue
        st = p.stat()
        if datetime.date.fromtimestamp(st.st_mtime) >= since:
            candidates.append((st.st_mtime, p))

    candidates.sort(key=lambda x: x[0], reverse=True)
    total = len(candidates)
    selected = [p for _, p in candidates[:limit]]
    return selected, total

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
    + "结尾用 Mia 的身份告别，例如：好了大毛，今天就聊到这里，我是 Mia，咱们下期见！\n"
    + "只输出脚本内容，不要加任何标题、说明或编号。"
)

_SCRIPT_SYSTEM_MULTI = (
    _SCRIPT_BASE
    + "根据提供的多篇知识笔记内容，生成一段单人播客脚本。\n"
    + "开头要有简短的问候和引入，例如：早上好呀大毛，（精神满满）今天咱们来聊聊最近发生的几件有意思的事。\n"
    + "内容要求：覆盖每篇笔记的核心要点，话题之间自然过渡，有引子、有展开、有总结。\n"
    + "结尾用 Mia 的身份告别。\n"
    + "{has_more_hint}"
    + "只输出脚本内容，不要加任何标题、说明或编号。"
)


@dataclass
class ScriptSegment:
    speaker: str
    text: str


class PodcastGenerator:
    def __init__(self, cfg: Any, llm: Any = None, tts: TTSClient | None = None):
        self.cfg = cfg
        self.llm = llm
        self.tts = tts or TTSClient(cfg.tts)

    def generate_script(self, title: str, content: str) -> list[ScriptSegment]:
        """Generate podcast monologue script from note content."""
        prompt = f"标题：{title}\n\n{content}"
        raw = self.llm.text_call(user_prompt=prompt, system=_SCRIPT_SYSTEM)
        segments: list[ScriptSegment] = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            segments.append(ScriptSegment(speaker="host", text=line))
        return segments

    def generate_multi_script(
        self, notes: list[Path], has_more: bool
    ) -> list[ScriptSegment]:
        """Generate a combined podcast script from multiple notes."""
        parts: list[str] = []
        for p in notes:
            post = frontmatter.loads(p.read_text(encoding="utf-8"))
            title = post.get("title", p.stem)
            content = post.content.strip()[:800]
            parts.append(f"## {title}\n{content}")

        prompt = "\n\n".join(parts)
        has_more_hint = (
            "在结尾处自然地提到还有更多有趣的内容，建议大毛有空去知识库看看。\n"
            if has_more
            else ""
        )
        system = _SCRIPT_SYSTEM_MULTI.format(has_more_hint=has_more_hint)

        raw = self.llm.text_call(user_prompt=prompt, system=system)
        segments: list[ScriptSegment] = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            segments.append(ScriptSegment(speaker="host", text=line))
        return segments

    def synthesize_script(self, segments: list[ScriptSegment]) -> bytes:
        """Synthesize full script as a single TTS call."""
        full_text = "\n".join(seg.text for seg in segments)
        return self.tts.synthesize(full_text)

    def get_duration(self, audio_path: Path) -> int:
        """Get duration in seconds via ffprobe."""
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(audio_path)],
            capture_output=True, text=True, check=True,
        )
        return max(1, int(float(result.stdout.strip())))

    def convert_to_opus(self, mp3_bytes: bytes) -> bytes:
        """Convert mp3 bytes to opus format via ffmpeg."""
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as src:
            src.write(mp3_bytes)
            src_path = Path(src.name)
        dst_path = src_path.with_suffix(".opus")
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(src_path), "-acodec", "libopus",
                 "-ac", "1", "-ar", "16000", str(dst_path)],
                capture_output=True, check=True,
            )
            return dst_path.read_bytes()
        finally:
            src_path.unlink(missing_ok=True)
            dst_path.unlink(missing_ok=True)

    def generate(self, note_path: Path) -> tuple[bytes, int]:
        """Full pipeline: note → script → TTS.

        Returns (audio_bytes, duration_seconds_estimate).
        """
        if not note_path.exists():
            raise FileNotFoundError(f"Note not found: {note_path}")

        post = frontmatter.loads(note_path.read_text(encoding="utf-8"))
        title = post.get("title", note_path.stem)
        content = post.content.strip()

        segments = self.generate_script(title, content)
        if not segments:
            raise ValueError("LLM produced no valid script segments")

        audio_bytes = self.synthesize_script(segments)
        duration = max(1, len(audio_bytes) // 16000)
        return audio_bytes, duration

    def generate_multi(
        self, note_paths: list[Path], has_more: bool
    ) -> tuple[bytes, int]:
        """Full pipeline: multiple notes → script → TTS."""
        if not note_paths:
            raise ValueError("No notes provided")

        segments = self.generate_multi_script(note_paths, has_more)
        if not segments:
            raise ValueError("LLM produced no valid script segments")

        audio_bytes = self.synthesize_script(segments)
        duration = max(1, len(audio_bytes) // 16000)
        return audio_bytes, duration
