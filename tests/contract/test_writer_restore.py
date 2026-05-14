"""契约：写到一半 → restore 还原。

锁定两条不变量：
- start 已存在 draft 时返回提示而不覆盖（不再调 LLM）。
- restore_published() 能从 99-publish/.archive/draft_<stamp>/ 把 draft.md / draft.json 拉回来。

注：writer.py 中存在两个恢复入口
  - restore_draft()：从同目录 .bak（_save_draft 写入的旁路备份）恢复。
  - restore_published()：从 publish_path/.archive/draft_<stamp>/（_archive_draft 在 publish 后挪过去的归档）恢复，自动取最新一条。
本契约对应「发布后想反悔」这条主链路 → 用 restore_published()。
"""
from __future__ import annotations

import json


def test_start_does_not_overwrite_existing_draft(cfg, make_writer, fake_llm):
    writer = make_writer()

    # 真实 schema 由 prompts.CONCEPT_TOOL_SCHEMA 决定：topic / thesis / audience / concept_text。
    fake_llm.queue_structured("generate_concept", {
        "topic": "已有标题",
        "thesis": "已有的论点",
        "audience": "广泛读者",
        "concept_text": "已有概念文本。",
    })
    writer.start("第一篇想法")
    assert writer.active

    original_meta = writer.draft_meta_path.read_text(encoding="utf-8")
    original_body = writer.draft_path.read_text(encoding="utf-8")

    # writer._start 在 self.active 时直接 return 提示，不再走 LLM。
    # 我们没有再 queue 任何 structured response —— 若 start 真的去调用 LLM，FakeLLMClient 会 AssertionError。
    reply = writer.start("第二篇想法")
    assert isinstance(reply, str) and reply.strip()
    assert "草稿" in reply, f"expected 'already a draft' style warning, got: {reply!r}"

    # 文件内容必须未被覆盖。
    assert writer.draft_meta_path.read_text(encoding="utf-8") == original_meta
    assert writer.draft_path.read_text(encoding="utf-8") == original_body

    # 没有触发 LLM（不是依赖 AssertionError，正面校验一遍）。
    assert len(fake_llm.structured_calls) == 1


def test_restore_published_from_archive(cfg, make_writer):
    """直接在归档目录里 plant 一份草稿；调用 restore_published() 把它救回来。"""
    writer = make_writer()
    assert writer.active is False

    # _archive_draft 用的目录约定：{publish_path}/.archive/draft_<stamp>/
    # restore_published 按 name 倒序选最新；测试隔离在 tmp_path 下，
    # 此处时间戳是该测试唯一的归档条目，必然被选中。
    archive_dir = cfg.knowledge.publish_path / ".archive" / "draft_2026-01-01_12-00-00"
    archive_dir.mkdir(parents=True)

    (archive_dir / "draft.md").write_text("# 恢复内容\n\n正文。\n", encoding="utf-8")
    meta_payload = {"stage": "review", "title": "恢复内容"}
    (archive_dir / "draft.json").write_text(
        json.dumps(meta_payload, ensure_ascii=False),
        encoding="utf-8",
    )

    out = writer.restore_published()
    assert isinstance(out, str) and out.strip()
    assert "恢复" in out, f"expected restore success message, got: {out!r}"

    # 核心契约：draft.md / draft.json 已经回到正常位置，内容字节级一致。
    assert writer.draft_path.exists(), "draft.md should be restored"
    assert writer.draft_meta_path.exists(), "draft.json should be restored"
    assert writer.draft_path.read_text(encoding="utf-8") == "# 恢复内容\n\n正文。\n"

    meta = json.loads(writer.draft_meta_path.read_text(encoding="utf-8"))
    assert meta.get("title") == "恢复内容"
    assert writer.active is True
