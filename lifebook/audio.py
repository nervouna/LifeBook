"""AudioProcessor: audio concatenation, format conversion, and duration detection."""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path


class AudioProcessor:
    """Extracted audio utility methods formerly on PodcastGenerator."""

    def concat_audio(self, parts: list[bytes]) -> bytes:
        """Concat mp3 byte segments via ffmpeg concat demuxer."""
        tmp_dir = tempfile.mkdtemp()
        try:
            paths: list[Path] = []
            for i, audio in enumerate(parts):
                p = Path(tmp_dir) / f"seg_{i}.mp3"
                p.write_bytes(audio)
                paths.append(p)
            list_file = Path(tmp_dir) / "list.txt"
            list_file.write_text(
                "\n".join(f"file '{p}'" for p in paths), encoding="utf-8"
            )
            output = Path(tmp_dir) / "out.mp3"
            subprocess.run(
                ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
                 "-i", str(list_file), "-c", "copy", str(output)],
                capture_output=True, check=True,
            )
            return output.read_bytes()
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

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

    def get_duration(self, audio_bytes: bytes) -> int:
        """Get duration in seconds from audio bytes via ffprobe (piped)."""
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", "-i", "pipe:0"],
            input=audio_bytes, capture_output=True, check=True,
        )
        return max(1, int(float(result.stdout.strip())))
