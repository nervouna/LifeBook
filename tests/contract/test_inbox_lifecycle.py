"""契约：URL 录入 → 处理 → topic 落盘 全链路。

锁定外部行为：源文件状态机、topic 文件路径与 frontmatter 关键字段。
"""
from __future__ import annotations

import frontmatter

from lifebook.ingest import ingest_url

from ._helpers import extract_payload, fake_fetch_result


def test_url_ingest_then_process_writes_topic(cfg, make_executor, fake_fetcher, fake_llm):
    # 1) ingest a URL — should land in 10-sources as status:inbox with empty body
    url = "https://example.com/article"
    source_path = ingest_url(cfg.knowledge, url, title_hint="示例文章")
    assert source_path.parent == cfg.knowledge.sources_path
    src_post = frontmatter.load(source_path)
    assert src_post.get("status") == "inbox"
    assert src_post.get("source") == url

    # 2) script the fetcher and the LLM
    fake_fetcher.script(url, fake_fetch_result(
        url=url,
        content="一段被抓取下来的正文，谈论人工智能的进展。",
        title="示例文章",
    ))
    fake_llm.queue_structured("extract_note", extract_payload(
        title="示例文章",
        category="AI技术",
        tags=["llm", "AI"],
    ))

    # 3) run the executor
    executor = make_executor()
    results = executor.process_inbox()

    # 4) one result, success, points to a topic
    assert len(results) == 1
    r = results[0]
    assert r.ok is True, f"expected success, got error={r.error!r}"
    assert r.topic_path is not None
    assert r.topic_path.exists()
    assert r.topic_path.is_relative_to(cfg.knowledge.topics_path / "AI技术")

    # 5) source file is now processed and points to the topic
    src_post = frontmatter.load(source_path)
    assert src_post.get("status") == "processed"
    assert src_post.get("topic_ref"), "source must record topic_ref after processing"

    # 6) topic file frontmatter has expected fields
    topic_post = frontmatter.load(r.topic_path)
    assert topic_post.get("title") == "示例文章"
    assert topic_post.get("category") == "AI技术"
    tags = topic_post.get("tags") or []
    assert "llm" in tags
    assert topic_post.get("source_url") == url
    # body should contain the extracted summary
    assert "这是摘要" in topic_post.content
