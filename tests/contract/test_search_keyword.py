"""契约：process 后的 topic 可被 NoteStore.search_topics 命中（关键词层）。

真 ChromaDB 契约推迟到阶段 2（届时 services 抽出后局部 unmock）。
"""
from __future__ import annotations

from lifebook.ingest import ingest_url
from lifebook.store import NoteStore

from ._helpers import extract_payload, fake_fetch_result


def test_processed_topic_is_searchable_by_keyword(cfg, make_executor, fake_fetcher, fake_llm):
    url = "https://example.com/transformer"
    ingest_url(cfg.knowledge, url, title_hint="Transformer 架构")

    fake_fetcher.script(url, fake_fetch_result(
        url=url,
        content="深入讲解 Transformer 架构。",
        title="Transformer 架构",
    ))
    fake_llm.queue_structured("extract_note", extract_payload(
        title="Transformer 架构",
        category="AI技术",
        tags=["transformer", "deep-learning"],
        related_keywords=["注意力", "神经网络"],
        narrative="Transformer 是一种基于自注意力的神经网络架构。",
        summary="一个关于 Transformer 架构的笔记。",
    ))

    executor = make_executor()
    results = executor.process_inbox()
    assert results[0].ok

    store = NoteStore(cfg.knowledge)
    hits = store.search_topics("transformer 架构", max_notes=3)
    assert hits, "expected at least one hit for 'transformer 架构'"
    assert any("Transformer" in h.title for h in hits)
