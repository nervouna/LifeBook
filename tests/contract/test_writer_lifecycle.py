"""契约：Writer 的 start → publish 主链路。

锁定 draft 三件套的存在/消失、publish 落盘到 99-publish/。
不验证 LLM 输出的语义、不验证 prompt 内容。
"""
from __future__ import annotations

import json


def test_writer_start_creates_draft_then_publish_writes_file(cfg, make_writer, fake_llm):
    writer = make_writer()
    assert writer.active is False, "no active draft expected at start of test"

    # Stage 1: start — produces concept via structured_call.
    # Schema 真实字段是 topic / thesis / audience / concept_text（见 prompts/writer.py）。
    fake_llm.queue_structured("generate_concept", {
        "topic": "我的第一篇文章",
        "thesis": "LifeBook 的设计哲学是把外部记忆做成可写、可查、可演化的系统。",
        "audience": "对个人知识系统感兴趣的开发者。",
        "concept_text": "讲讲 LifeBook 的设计哲学：它不是笔记工具，而是把人脑外部记忆变成可演化系统的工程实践。",
    })

    reply = writer.start("我想写一篇关于 LifeBook 设计的文章")
    assert isinstance(reply, str) and reply.strip(), "start should return a non-empty reply"

    # draft files exist
    assert writer.draft_path.exists(), "draft.md must exist after start"
    assert writer.draft_meta_path.exists(), "draft.json must exist after start"
    assert writer.active is True
    assert writer.stage == "concept"

    meta = json.loads(writer.draft_meta_path.read_text(encoding="utf-8"))
    assert meta.get("stage") == "concept"
    # Writer 把 result["topic"] 作为 meta["title"]。
    assert meta.get("title") == "我的第一篇文章"

    # Force-advance to a publishable state by writing draft body and flipping stage.
    # Goal here is to lock the publish contract, not the multi-stage path.
    writer.draft_path.write_text(
        "# 我的第一篇文章\n\n这是文章正文，要够长以便发布通过。\n", encoding="utf-8"
    )
    meta["stage"] = "review"
    # 清空 checklist 避免 publish 因清单未回应而拦截。
    meta["checklist"] = ""
    writer.draft_meta_path.write_text(
        json.dumps(meta, ensure_ascii=False), encoding="utf-8"
    )
    # checkpoint：确认 stage 写入已被 Writer 读到，避免 publish 失败时混淆 setup 与 _publish。
    assert writer.stage == "review", f"pre-publish stage setup failed: {writer.stage!r}"

    # publish() 返回的是状态消息（str），不是 Path。
    # 知识库为空，_evaluate_backfill 中 _vector_search 走 NoteStore.search_topics_formatted，
    # 返回 ""，于是直接跳过 backfill 的 LLM 调用。
    result_msg = writer.publish()
    assert isinstance(result_msg, str)
    assert "已发布到" in result_msg, f"unexpected publish reply: {result_msg!r}"

    # 核心契约 1：draft.json 已被清理（_archive_draft 把 draft 文件 move 到 .archive/）
    assert not writer.draft_meta_path.exists(), "draft.json should be cleared after publish"
    assert writer.active is False

    # 核心契约 2：99-publish/ 下出现一篇真实落盘的文章（排除 draft 残留与 .archive 子目录）
    publish_dir = cfg.knowledge.publish_path
    published_files = [
        p for p in publish_dir.iterdir()
        if p.is_file()
        and p.suffix == ".md"
        and not p.name.startswith("draft")
    ]
    assert len(published_files) == 1, (
        f"expected exactly one published .md under {publish_dir}, "
        f"found: {[p.name for p in published_files]}"
    )
    assert published_files[0].read_text(encoding="utf-8").strip(), \
        "published file must not be empty"
