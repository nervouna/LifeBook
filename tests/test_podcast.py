"""Unit tests for podcast.py."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from lifebook.podcast import PodcastGenerator


@pytest.fixture
def gen():
    cfg = MagicMock()
    cfg.knowledge.root = Path("/tmp/kb")
    cfg.tts = MagicMock()
    cfg.tts.voice_id = "Calm_Woman"
    llm = MagicMock()
    tts = MagicMock()
    return PodcastGenerator(cfg, llm=llm, tts=tts)


class TestGenerateScript:
    def test_calls_llm_with_note_content(self, gen):
        gen.llm.text_call.return_value = (
            "A: 欢迎收听。\nB: 今天我们聊 AI。\nA: 好的。"
        )
        script = gen.generate_script("Title", "Some content about AI")
        gen.llm.text_call.assert_called_once()
        assert len(script) == 3
        assert script[0].speaker == "A"
        assert script[1].speaker == "B"

    def test_script_returns_segments(self, gen):
        gen.llm.text_call.return_value = "A: Hello.\nB: Hi there.\nA: Let's go."
        segments = gen.generate_script("Test", "content")
        assert len(segments) == 3
        assert segments[0].text == "Hello."
        assert segments[1].text == "Hi there."

    def test_script_skips_empty_lines(self, gen):
        gen.llm.text_call.return_value = "A: Hello.\n\nB: Hi.\n\nA: Bye."
        segments = gen.generate_script("Test", "content")
        assert len(segments) == 3

    def test_script_strips_whitespace(self, gen):
        gen.llm.text_call.return_value = "  A: Hello.  \n  B: Hi.  "
        segments = gen.generate_script("Test", "content")
        assert segments[0].text == "Hello."
        assert segments[1].text == "Hi."


class TestSynthesizeSegments:
    def test_calls_tts_for_each_segment(self, gen):
        from lifebook.podcast import ScriptSegment

        segments = [
            ScriptSegment(speaker="A", text="Hello."),
            ScriptSegment(speaker="B", text="Hi."),
        ]
        gen.tts.synthesize.side_effect = [b"audio1", b"audio2"]

        result = gen.synthesize_segments(segments)
        assert gen.tts.synthesize.call_count == 2
        assert len(result) == 2

    def test_empty_segments_returns_empty(self, gen):
        result = gen.synthesize_segments([])
        assert result == []
        gen.tts.synthesize.assert_not_called()


class TestConcatenateAudio:
    def test_single_file_returns_same_bytes(self, gen, tmp_path):
        audio = tmp_path / "test.mp3"
        audio.write_bytes(b"\xff\xfb\x90\x00 fake mp3")
        result = gen.concatenate_audio([audio])
        assert result == b"\xff\xfb\x90\x00 fake mp3"

    def test_multiple_files_calls_ffmpeg(self, gen, tmp_path):
        f1 = tmp_path / "a.mp3"
        f2 = tmp_path / "b.mp3"
        f1.write_bytes(b"audio1")
        f2.write_bytes(b"audio2")

        def fake_ffmpeg(*args, **kwargs):
            cmd = args[0]
            Path(cmd[-1]).write_bytes(b"merged")
            return MagicMock(returncode=0)

        with patch("lifebook.podcast.subprocess.run") as mock_run:
            mock_run.side_effect = fake_ffmpeg
            result = gen.concatenate_audio([f1, f2])

        assert result == b"merged"
        mock_run.assert_called_once()


class TestGeneratePodcast:
    def test_full_pipeline(self, gen, tmp_path):
        # Setup note file
        note = tmp_path / "note.md"
        note.write_text(
            "---\ntitle: AI News\n---\n> summary\n\nContent about AI.\n",
            encoding="utf-8",
        )

        gen.llm.text_call.return_value = "A: Welcome.\nB: Thanks."
        gen.tts.synthesize.side_effect = [b"mp3_a", b"mp3_b"]

        with patch.object(gen, "concatenate_audio", return_value=b"final_mp3"):
            audio_bytes, duration_hint = gen.generate(note)

        assert audio_bytes == b"final_mp3"
        assert gen.tts.synthesize.call_count == 2

    def test_missing_note_raises(self, gen):
        with pytest.raises(FileNotFoundError):
            gen.generate(Path("/nonexistent/note.md"))
