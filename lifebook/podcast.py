"""Podcast generator: topic note → script → audio."""
from __future__ import annotations

import logging
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import frontmatter

from .tts import TTSClient

logger = logging.getLogger(__name__)

_SCRIPT_SYSTEM = (
    "你是一位播客节目编剧。根据提供的知识笔记内容，生成一段双人对话式播客脚本。\n"
    "格式要求：每行一条对话，格式为 'A: 对话内容' 或 'B: 对话内容'，A 和 B 轮流发言。\n"
    "风格要求：口语化、有节奏感、自然流畅，像两个朋友聊天一样。\n"
    "内容要求：覆盖笔记的核心要点，有引子、有展开、有总结。\n"
    "只输出脚本内容，不要加任何标题、说明或编号。"
)

_SEGMENT_RE = re.compile(r"^(A|B)\s*[:：]\s*(.+)$")


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
        """Generate podcast dialogue script from note content."""
        prompt = f"标题：{title}\n\n{content}"
        raw = self.llm.text_call(user_prompt=prompt, system=_SCRIPT_SYSTEM)
        segments: list[ScriptSegment] = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            m = _SEGMENT_RE.match(line)
            if m:
                segments.append(ScriptSegment(speaker=m.group(1), text=m.group(2).strip()))
        return segments

    def synthesize_segments(self, segments: list[ScriptSegment]) -> list[bytes]:
        """Synthesize each script segment to audio bytes."""
        audio_parts: list[bytes] = []
        for seg in segments:
            audio = self.tts.synthesize(seg.text)
            audio_parts.append(audio)
        return audio_parts

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

    def concatenate_audio(self, audio_files: list[Path]) -> bytes:
        """Concatenate multiple audio files into one. Returns merged bytes."""
        if len(audio_files) == 1:
            return audio_files[0].read_bytes()

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            output_path = Path(tmp.name)

        list_file = output_path.with_suffix(".txt")
        list_file.write_text(
            "\n".join(f"file '{f}'" for f in audio_files), encoding="utf-8"
        )

        try:
            subprocess.run(
                ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
                 "-i", str(list_file), "-c", "copy", str(output_path)],
                capture_output=True, check=True,
            )
            return output_path.read_bytes()
        finally:
            list_file.unlink(missing_ok=True)
            output_path.unlink(missing_ok=True)

    def generate(self, note_path: Path) -> tuple[bytes, int]:
        """Full pipeline: note → script → TTS → concatenated audio.

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

        audio_parts = self.synthesize_segments(segments)

        temp_files: list[Path] = []
        try:
            for i, audio in enumerate(audio_parts):
                p = note_path.parent / f".podcast_tmp_{i}.mp3"
                p.write_bytes(audio)
                temp_files.append(p)
            merged = self.concatenate_audio(temp_files)
        finally:
            for p in temp_files:
                p.unlink(missing_ok=True)

        # Rough estimate: ~16KB per second at 128kbps mp3
        duration = max(1, len(merged) // 16000)
        return merged, duration
