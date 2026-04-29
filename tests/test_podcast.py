"""Unit tests for podcast.py."""
from __future__ import annotations

import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from lifebook.podcast import PodcastGenerator, ScriptSegment, TTSError, select_notes, _extract_podcast_content


def _mock_path(p: str, read_bytes: bytes = b"") -> MagicMock:
    m = MagicMock()
    m.write_bytes = MagicMock()
    m.write_text = MagicMock()
    m.read_bytes.return_value = read_bytes
    m.__str__ = lambda self: p
    return m


@pytest.fixture
def gen():
    cfg = MagicMock()
    cfg.knowledge.root = Path("/tmp/kb")
    cfg.tts = MagicMock()
    cfg.tts.voice_id = "mimo_default"
    llm = MagicMock()
    tts = MagicMock()
    return PodcastGenerator(cfg, llm=llm, tts=tts)


class TestGenerateScript:
    def test_calls_llm_with_note_content(self, gen):
        gen.llm.text_call.return_value = (
            "早上好呀大毛，（精神满满）今天咱们来聊一个有意思的话题。\n"
            "说到 AI 最近的发展，（认真）确实让人目不暇接。\n"
            "好了大毛，今天就聊到这里，我是 Mia，咱们下期见！"
        )
        script = gen.generate_script("Title", "Some content about AI")
        gen.llm.text_call.assert_called_once()
        assert len(script) == 3
        assert script[0].speaker == "host"
        assert "早上好" in script[0].text

    def test_script_returns_segments(self, gen):
        gen.llm.text_call.return_value = "Hello.\nHi there.\nLet's go."
        segments = gen.generate_script("Test", "content")
        assert len(segments) == 3
        assert segments[0].text == "Hello."
        assert segments[1].text == "Hi there."

    def test_script_skips_empty_lines(self, gen):
        gen.llm.text_call.return_value = "Line one.\n\nLine two.\n\nLine three."
        segments = gen.generate_script("Test", "content")
        assert len(segments) == 3

    def test_script_strips_whitespace(self, gen):
        gen.llm.text_call.return_value = "  Hello.  \n  Hi.  "
        segments = gen.generate_script("Test", "content")
        assert segments[0].text == "Hello."
        assert segments[1].text == "Hi."

    def test_script_preserves_parenthetical_descriptions(self, gen):
        gen.llm.text_call.return_value = "早上好呀，（开心）今天天气不错。"
        segments = gen.generate_script("Test", "content")
        assert len(segments) == 1
        assert "（开心）" in segments[0].text


class TestSynthesizeScript:
    def test_synthesizes_each_segment_independently(self, gen):
        segments = [
            ScriptSegment(speaker="host", text="Hello."),
            ScriptSegment(speaker="host", text="Hi."),
        ]
        gen.tts.synthesize.side_effect = [b"audio1", b"audio2"]
        gen._concat_audio = MagicMock(return_value=b"merged")

        result = gen.synthesize_script(segments)

        assert result == b"merged"
        assert gen.tts.synthesize.call_count == 2
        gen.tts.synthesize.assert_any_call("Hello.")
        gen.tts.synthesize.assert_any_call("Hi.")
        gen._concat_audio.assert_called_once_with([b"audio1", b"audio2"])

    def test_single_segment_skips_concat(self, gen):
        gen.tts.synthesize.return_value = b"audio"
        result = gen.synthesize_script([ScriptSegment(speaker="host", text="Hi.")])
        assert result == b"audio"
        gen.tts.synthesize.assert_called_once_with("Hi.")

    def test_skips_content_filtered_segments(self, gen):
        segments = [
            ScriptSegment(speaker="host", text="Good segment."),
            ScriptSegment(speaker="host", text="Bad segment."),
            ScriptSegment(speaker="host", text="Another good one."),
        ]
        gen.tts.synthesize.side_effect = [b"audio1", TTSError("content_filter"), b"audio2"]
        gen._concat_audio = MagicMock(return_value=b"merged")

        result = gen.synthesize_script(segments)

        assert result == b"merged"
        assert gen.tts.synthesize.call_count == 3
        gen._concat_audio.assert_called_once_with([b"audio1", b"audio2"])

    def test_all_segments_fail_raises(self, gen):
        segments = [
            ScriptSegment(speaker="host", text="Bad 1."),
            ScriptSegment(speaker="host", text="Bad 2."),
        ]
        gen.tts.synthesize.side_effect = TTSError("content_filter")

        with pytest.raises(TTSError, match="All segments failed"):
            gen.synthesize_script(segments)


class TestConcatAudio:
    def test_concats_via_ffmpeg(self, gen, tmp_path):
        out_file = tmp_path / "out.mp3"
        out_file.write_bytes(b"merged")

        def fake_subprocess(*args, **kwargs):
            cmd = args[0]
            if "-c" in cmd and "copy" in cmd:
                idx = cmd.index("-c")
                out_arg = cmd[idx + 2]
                Path(out_arg).write_bytes(b"merged")
            return MagicMock()

        with patch("lifebook.podcast.subprocess.run", side_effect=fake_subprocess), \
             patch("lifebook.podcast.tempfile.mkdtemp", return_value=str(tmp_path)):
            result = gen._concat_audio([b"a", b"b"])

        assert result == b"merged"


class TestGeneratePodcast:
    def test_full_pipeline(self, gen, tmp_path):
        note = tmp_path / "note.md"
        note.write_text(
            "---\ntitle: AI News\n---\n> summary\n\nContent about AI.\n",
            encoding="utf-8",
        )

        gen.llm.text_call.return_value = "早上好大毛。\n（认真）今天聊 AI。\n再见。"
        gen.tts.synthesize.return_value = b"fake_mp3"
        gen._concat_audio = MagicMock(return_value=b"merged")
        gen._get_duration_from_bytes = MagicMock(return_value=120)

        audio_bytes, duration = gen.generate(note)

        assert audio_bytes == b"merged"
        assert duration == 120
        assert gen.tts.synthesize.call_count == 3

    def test_missing_note_raises(self, gen):
        with pytest.raises(FileNotFoundError):
            gen.generate(Path("/nonexistent/note.md"))


class TestExtractPodcastContent:
    def test_strips_frontmatter(self):
        raw = "> 摘要\n\n## 要点\n- point 1\n\n## 章节\nContent here."
        result = _extract_podcast_content(raw)
        assert "摘要" in result
        assert "要点" in result
        assert "章节" in result

    def test_skips_related_notes(self):
        raw = "## 要点\n- point 1\n\n## 相关笔记\n- [[note1]]\n- [[note2]]"
        result = _extract_podcast_content(raw)
        assert "要点" in result
        assert "相关笔记" not in result
        assert "note1" not in result

    def test_skips_source(self):
        raw = "## 章节\nContent.\n\n## 来源\nhttps://example.com"
        result = _extract_podcast_content(raw)
        assert "章节" in result
        assert "来源" not in result
        assert "example.com" not in result

    def test_skips_both_related_and_source(self):
        raw = "Content.\n\n## 相关笔记\n- [[a]]\n\n## 来源\nhttps://x.com"
        result = _extract_podcast_content(raw)
        assert result == "Content."

    def test_no_skip_sections(self):
        raw = "## 要点\n- p1\n\n## 详情\nMore content."
        result = _extract_podcast_content(raw)
        assert "详情" in result

    def test_empty_content(self):
        assert _extract_podcast_content("") == ""
        assert _extract_podcast_content("   ") == ""


class TestSelectNotes:
    def test_select_by_date_and_limit(self, tmp_path):
        cat = tmp_path / "AI技术"
        cat.mkdir()
        # Create notes with different mtimes
        old_note = cat / "old.md"
        old_note.write_text("old", encoding="utf-8")
        import os
        os.utime(old_note, (1700000000, 1700000000))  # 2023-11-14

        new1 = cat / "new1.md"
        new1.write_text("new1", encoding="utf-8")
        new2 = cat / "new2.md"
        new2.write_text("new2", encoding="utf-8")

        since = datetime.date(2026, 1, 1)
        selected, total = select_notes(tmp_path, since, limit=10)

        assert total == 2
        assert old_note not in selected
        assert new1 in selected
        assert new2 in selected

    def test_select_respects_limit(self, tmp_path):
        cat = tmp_path / "cat"
        cat.mkdir()
        for i in range(5):
            (cat / f"n{i}.md").write_text(f"n{i}", encoding="utf-8")

        since = datetime.date(2020, 1, 1)
        selected, total = select_notes(tmp_path, since, limit=3)

        assert total == 5
        assert len(selected) == 3

    def test_select_skips_hidden_files(self, tmp_path):
        cat = tmp_path / "cat"
        cat.mkdir()
        (cat / ".hidden.md").write_text("hidden", encoding="utf-8")
        (cat / "visible.md").write_text("visible", encoding="utf-8")

        since = datetime.date(2020, 1, 1)
        selected, total = select_notes(tmp_path, since, limit=10)

        assert total == 1
        assert selected[0].name == "visible.md"


class TestGenerateMultiScript:
    def test_calls_llm_with_combined_content(self, gen, tmp_path):
        n1 = tmp_path / "note1.md"
        n1.write_text("---\ntitle: Topic A\n---\nContent A.\n", encoding="utf-8")
        n2 = tmp_path / "note2.md"
        n2.write_text("---\ntitle: Topic B\n---\nContent B.\n", encoding="utf-8")

        gen.llm.text_call.return_value = "早上好大毛。\n聊 topic A。\n再聊 topic B。\n再见。"
        segments = gen.generate_multi_script([n1, n2], has_more=False)

        assert len(segments) == 4
        gen.llm.text_call.assert_called_once()
        call_kwargs = gen.llm.text_call.call_args
        assert "Topic A" in call_kwargs.kwargs.get("user_prompt", call_kwargs[1].get("user_prompt", ""))

    def test_has_more_includes_hint(self, gen, tmp_path):
        n1 = tmp_path / "note1.md"
        n1.write_text("---\ntitle: T\n---\nC\n", encoding="utf-8")

        gen.llm.text_call.return_value = "Hi.\nBye."
        gen.generate_multi_script([n1], has_more=True)

        call_kwargs = gen.llm.text_call.call_args
        system = call_kwargs.kwargs.get("system", call_kwargs[1].get("system", ""))
        assert "知识库" in system


class TestGenerateMulti:
    def test_full_pipeline(self, gen, tmp_path):
        n1 = tmp_path / "a.md"
        n1.write_text("---\ntitle: A\n---\nContent A.\n", encoding="utf-8")
        n2 = tmp_path / "b.md"
        n2.write_text("---\ntitle: B\n---\nContent B.\n", encoding="utf-8")

        gen.llm.text_call.return_value = "Hello.\nWorld."
        gen.tts.synthesize.return_value = b"fake_mp3"
        gen._concat_audio = MagicMock(return_value=b"merged")
        gen._get_duration_from_bytes = MagicMock(return_value=60)

        audio, duration = gen.generate_multi([n1, n2], has_more=False)

        assert audio == b"merged"
        assert duration == 60
        assert gen.tts.synthesize.call_count == 2

    def test_empty_notes_raises(self, gen):
        with pytest.raises(ValueError, match="No notes"):
            gen.generate_multi([], has_more=False)


class TestGenerateMultiScriptEdgeCases:
    def test_single_note(self, gen, tmp_path):
        n1 = tmp_path / "single.md"
        n1.write_text("---\ntitle: Only\n---\nContent.\n", encoding="utf-8")

        gen.llm.text_call.return_value = "Hi.\nBye."
        segments = gen.generate_multi_script([n1], has_more=False)

        assert len(segments) == 2
        gen.llm.text_call.assert_called_once()

    def test_empty_content_note(self, gen, tmp_path):
        n1 = tmp_path / "empty.md"
        n1.write_text("---\ntitle: Empty\n---\n\n", encoding="utf-8")

        gen.llm.text_call.return_value = "Hi.\nBye."
        segments = gen.generate_multi_script([n1], has_more=False)

        assert len(segments) == 2

    def test_long_content_truncated(self, gen, tmp_path):
        n1 = tmp_path / "long.md"
        long_content = "x" * 6000
        n1.write_text(f"---\ntitle: Long\n---\n{long_content}\n", encoding="utf-8")

        gen.llm.text_call.return_value = "Hi."
        gen.generate_multi_script([n1], has_more=False)

        call_args = gen.llm.text_call.call_args
        prompt = call_args.kwargs.get("user_prompt", call_args[1].get("user_prompt", ""))
        assert len(prompt) < 6500  # title + truncated content

    def test_file_read_error_skips(self, gen, tmp_path):
        good = tmp_path / "good.md"
        good.write_text("---\ntitle: Good\n---\nContent.\n", encoding="utf-8")
        bad = tmp_path / "bad.md"
        bad.write_bytes(b"\x80\x81\x82")  # invalid utf-8

        gen.llm.text_call.return_value = "Hi."
        segments = gen.generate_multi_script([bad, good], has_more=False)

        assert len(segments) == 1
        gen.llm.text_call.assert_called_once()

    def test_all_files_bad_raises(self, gen, tmp_path):
        bad = tmp_path / "bad.md"
        bad.write_bytes(b"\x80\x81\x82")

        with pytest.raises(ValueError, match="No readable notes"):
            gen.generate_multi_script([bad], has_more=False)


class TestPodcastGeneratorInit:
    def test_llm_required(self):
        cfg = MagicMock()
        cfg.tts = MagicMock()
        with pytest.raises(TypeError):
            PodcastGenerator(cfg)
