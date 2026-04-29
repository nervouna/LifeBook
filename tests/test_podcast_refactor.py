"""Tests for podcast improvements and AudioProcessor extraction."""
from __future__ import annotations

import datetime
import os
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open

import pytest


# ---------------------------------------------------------------------------
# select_notes with frontmatter dates
# ---------------------------------------------------------------------------

class TestSelectNotesFrontmatter:
    def test_uses_processed_at_over_mtime(self, tmp_path):
        from lifebook.podcast import select_notes
        topics = tmp_path / "topics"
        cat = topics / "tech"
        cat.mkdir(parents=True)

        # Create a note with old mtime but recent processed_at
        note = cat / "recent.md"
        note.write_text("---\ntitle: Test\ncreated: '2026-04-25T10:00:00+08:00'\nprocessed_at: '2026-04-28T10:00:00+08:00'\n---\n\nContent")
        # Set mtime to 2026-04-01 (before since date)
        old_time = datetime.datetime(2026, 4, 1, tzinfo=datetime.timezone.utc).timestamp()
        os.utime(str(note), (old_time, old_time))

        since = datetime.date(2026, 4, 20)
        selected, total = select_notes(topics, since)
        assert len(selected) == 1
        assert selected[0] == note

    def test_falls_back_to_st_mtime_when_no_frontmatter_dates(self, tmp_path):
        from lifebook.podcast import select_notes
        topics = tmp_path / "topics"
        cat = topics / "tech"
        cat.mkdir(parents=True)

        note = cat / "old.md"
        note.write_text("---\ntitle: Old Note\n---\n\nOld content")
        # Set mtime to 2026-04-25
        recent_time = datetime.datetime(2026, 4, 25, tzinfo=datetime.timezone.utc).timestamp()
        os.utime(str(note), (recent_time, recent_time))

        since = datetime.date(2026, 4, 20)
        selected, total = select_notes(topics, since)
        assert len(selected) == 1

    def test_excludes_notes_before_since(self, tmp_path):
        from lifebook.podcast import select_notes
        topics = tmp_path / "topics"
        cat = topics / "tech"
        cat.mkdir(parents=True)

        note = cat / "old.md"
        note.write_text("---\ntitle: Old\nprocessed_at: '2026-04-01T10:00:00+08:00'\n---\n\nContent")
        old_time = datetime.datetime(2026, 3, 1, tzinfo=datetime.timezone.utc).timestamp()
        os.utime(str(note), (old_time, old_time))

        since = datetime.date(2026, 4, 20)
        selected, total = select_notes(topics, since)
        assert len(selected) == 0


# ---------------------------------------------------------------------------
# Content-aware truncation
# ---------------------------------------------------------------------------

class TestContentAwareTruncation:
    def test_truncates_at_paragraph_boundary(self):
        from lifebook.podcast import truncate_at_boundary
        # Build text with paragraphs
        paragraphs = ["Para %d. %s" % (i, "x" * 200) for i in range(50)]
        text = "\n\n".join(paragraphs)
        result = truncate_at_boundary(text, max_chars=3000)
        assert len(result) <= 3000
        # Should end at a paragraph boundary (no partial paragraph)
        assert result.endswith("x" * 200) or result.endswith(".")

    def test_no_truncation_when_under_limit(self):
        from lifebook.podcast import truncate_at_boundary
        text = "Short text."
        result = truncate_at_boundary(text, max_chars=5000)
        assert result == text

    def test_falls_back_to_hard_truncate_when_no_paragraphs(self):
        from lifebook.podcast import truncate_at_boundary
        text = "A" * 6000
        result = truncate_at_boundary(text, max_chars=5000)
        assert len(result) <= 5001  # +1 for possible newline
        assert len(result) > 4000

    def test_preserves_paragraph_structure(self):
        from lifebook.podcast import truncate_at_boundary
        text = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph."
        result = truncate_at_boundary(text, max_chars=30)
        # Should only contain first paragraph
        assert "Second paragraph" not in result
        assert "First paragraph" in result


# ---------------------------------------------------------------------------
# TTS failure threshold
# ---------------------------------------------------------------------------

class TestTTSFailureThreshold:
    def test_raises_when_failure_rate_exceeds_50_percent(self):
        from lifebook.podcast import PodcastGenerator
        gen = PodcastGenerator.__new__(PodcastGenerator)
        gen.cfg = MagicMock()
        gen.llm = MagicMock()
        gen.tts = MagicMock()

        from lifebook.tts import TTSError
        gen.tts.synthesize.side_effect = TTSError("content filtered")

        segments = [
            MagicMock(text="seg1"),
            MagicMock(text="seg2"),
            MagicMock(text="seg3"),
            MagicMock(text="seg4"),
        ]

        with pytest.raises(TTSError, match="TTS failure rate"):
            gen.synthesize_script(segments)

    def test_succeeds_when_failure_rate_below_50_percent(self):
        from lifebook.podcast import PodcastGenerator
        from lifebook.tts import TTSError
        gen = PodcastGenerator.__new__(PodcastGenerator)
        gen.cfg = MagicMock()
        gen.llm = MagicMock()
        gen.tts = MagicMock()
        gen.audio = MagicMock()
        gen.audio.concat_audio.return_value = b"concatenated"

        call_count = 0

        def fake_synthesize(text):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise TTSError("filtered")
            return b"audio"

        gen.tts.synthesize.side_effect = fake_synthesize

        segments = [MagicMock(text=f"seg{i}") for i in range(4)]
        result = gen.synthesize_script(segments)
        assert result == b"concatenated"

    def test_succeeds_when_exactly_50_percent(self):
        from lifebook.podcast import PodcastGenerator
        from lifebook.tts import TTSError
        gen = PodcastGenerator.__new__(PodcastGenerator)
        gen.cfg = MagicMock()
        gen.llm = MagicMock()
        gen.tts = MagicMock()
        gen.audio = MagicMock()
        gen.audio.concat_audio.return_value = b"concat"

        call_count = 0

        def fake_synthesize(text):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise TTSError("filtered")
            return b"audio"

        gen.tts.synthesize.side_effect = fake_synthesize

        segments = [MagicMock(text=f"seg{i}") for i in range(4)]
        result = gen.synthesize_script(segments)
        assert result == b"concat"


# ---------------------------------------------------------------------------
# AudioProcessor
# ---------------------------------------------------------------------------

class TestAudioProcessor:
    def test_concat_audio(self):
        from lifebook.audio import AudioProcessor
        ap = AudioProcessor()
        with patch("lifebook.audio.subprocess.run") as mock_run:
            def fake_run(cmd, **kwargs):
                # Simulate ffmpeg writing output file
                if "out.mp3" in str(cmd):
                    out_path = Path(cmd[-1])
                    out_path.write_bytes(b"concatenated")
                result = MagicMock()
                result.returncode = 0
                return result

            mock_run.side_effect = fake_run
            with patch("lifebook.audio.tempfile.mkdtemp", return_value="/tmp/fake"):
                with patch("lifebook.audio.shutil.rmtree"):
                    with patch.object(Path, "write_bytes"):
                        with patch.object(Path, "write_text"):
                            with patch.object(Path, "read_bytes", return_value=b"concatenated"):
                                result = ap.concat_audio([b"seg1", b"seg2"])
            assert result == b"concatenated"

    def test_convert_to_opus(self):
        from lifebook.audio import AudioProcessor
        ap = AudioProcessor()
        with patch("lifebook.audio.subprocess.run") as mock_run:
            def fake_run(cmd, **kwargs):
                if "out" in str(cmd) and str(cmd).endswith(".opus]"):
                    out_path = Path(str(cmd[-1]))
                    out_path.write_bytes(b"opus_data")
                result = MagicMock()
                result.returncode = 0
                return result

            mock_run.side_effect = fake_run
            with patch("lifebook.audio.Path") as MockPath:
                mock_src = MagicMock()
                mock_src.with_suffix.return_value = MagicMock()
                mock_src.with_suffix.return_value.read_bytes.return_value = b"opus_data"
                mock_src.unlink = MagicMock()
                mock_src.with_suffix.return_value.unlink = MagicMock()
                MockPath.return_value.__enter__ = MagicMock(return_value=mock_src)
                MockPath.return_value.__exit__ = MagicMock(return_value=False)
                MockPath.side_effect = lambda *a, **k: mock_src
                result = ap.convert_to_opus(b"mp3_data")
            assert result == b"opus_data"

    def test_get_duration(self):
        from lifebook.audio import AudioProcessor
        ap = AudioProcessor()
        with patch("lifebook.audio.subprocess.run") as mock_run:
            result_mock = MagicMock()
            result_mock.stdout = b"123.456"
            mock_run.return_value = result_mock
            duration = ap.get_duration(b"audio_bytes")
            assert duration == 123

    def test_get_duration_minimum_one(self):
        from lifebook.audio import AudioProcessor
        ap = AudioProcessor()
        with patch("lifebook.audio.subprocess.run") as mock_run:
            result_mock = MagicMock()
            result_mock.stdout = b"0.001"
            mock_run.return_value = result_mock
            duration = ap.get_duration(b"audio_bytes")
            assert duration == 1


# ---------------------------------------------------------------------------
# Podcast uses AudioProcessor
# ---------------------------------------------------------------------------

class TestPodcastUsesAudioProcessor:
    def test_synthesize_script_delegates_to_audio_processor(self):
        from lifebook.podcast import PodcastGenerator
        gen = PodcastGenerator.__new__(PodcastGenerator)
        gen.cfg = MagicMock()
        gen.llm = MagicMock()
        gen.tts = MagicMock()
        gen.audio = MagicMock()
        gen.audio.concat_audio.return_value = b"concat"
        gen.tts.synthesize.return_value = b"audio"

        segments = [MagicMock(text="seg1"), MagicMock(text="seg2")]
        result = gen.synthesize_script(segments)
        gen.audio.concat_audio.assert_called_once_with([b"audio", b"audio"])
        assert result == b"concat"

    def test_generate_uses_audio_processor_for_duration(self):
        from lifebook.podcast import PodcastGenerator
        gen = PodcastGenerator.__new__(PodcastGenerator)
        gen.cfg = MagicMock()
        gen.llm = MagicMock()
        gen.tts = MagicMock()
        gen.audio = MagicMock()
        gen.audio.get_duration.return_value = 120

        mock_path = MagicMock(spec=Path)
        mock_path.exists.return_value = True

        with patch("lifebook.podcast.read_note") as mock_read:
            mock_read.return_value = MagicMock(get=lambda k, d=None: d, content="body")
            with patch.object(gen, "generate_script", return_value=[MagicMock(text="hello")]):
                with patch.object(gen, "synthesize_script", return_value=b"audio"):
                    audio, duration = gen.generate(mock_path)
        gen.audio.get_duration.assert_called_once_with(b"audio")
        assert duration == 120
