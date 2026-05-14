"""契约：processing 状态超时 → recover_stale → 重新 process 成功。"""
from __future__ import annotations

from datetime import datetime, timedelta

import frontmatter

from lifebook.notes import CN_TZ, write_note, new_post

from ._helpers import extract_payload, fake_fetch_result


def test_stale_processing_is_recovered_then_processed(cfg, make_executor, fake_fetcher, fake_llm):
    # Plant a stale source file: status=processing, processing_at is 30 minutes ago.
    sources = cfg.knowledge.sources_path
    stale_at = (datetime.now(CN_TZ) - timedelta(minutes=30)).isoformat()
    path = sources / "stuck.md"
    write_note(path, new_post(
        "",
        status="processing",
        processing_at=stale_at,
        source="https://example.com/stuck",
        source_type="chat_link",
    ))

    executor = make_executor()

    # recover_stale with a 10-minute timeout should flip it back to inbox
    stale = executor.recover_stale(timeout_minutes=10, dry_run=False)
    assert any(p == path for p, _ in stale), f"expected to recover {path}, got {stale}"

    post = frontmatter.load(path)
    assert post.get("status") == "inbox"
    assert post.get("processing_at") is None or "processing_at" not in post.metadata

    # Now wire fakes and process successfully
    fake_fetcher.script("https://example.com/stuck", fake_fetch_result(
        url="https://example.com/stuck",
        content="recovered content body",
        title="Recovered",
    ))
    fake_llm.queue_structured("extract_note", extract_payload(title="Recovered"))

    results = executor.process_inbox()
    assert len(results) == 1 and results[0].ok, f"recovery roundtrip failed: {results[0].error}"
    assert frontmatter.load(path).get("status") == "processed"
