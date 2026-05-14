"""契约：fetch 失败的退避与最终 fetch_failed 状态、以及 retry_failed 的复位。"""
from __future__ import annotations

import frontmatter

from lifebook.ingest import ingest_url

from ._helpers import fake_fetch_result


def test_fetch_failure_increments_retry_then_fails_then_retried(cfg, make_executor, fake_fetcher):
    url = "https://example.com/broken"
    source_path = ingest_url(cfg.knowledge, url)

    # All fetches fail
    fake_fetcher.script(url, fake_fetch_result(url=url, ok=False, error="boom", status="ERR"))

    executor = make_executor()

    # Attempt 1: retry_count 0 -> 1, status stays inbox (retryable)
    executor.process_inbox()
    post = frontmatter.load(source_path)
    assert post.get("status") == "inbox"
    assert int(post.get("retry_count") or 0) == 1
    assert post.get("fetch_error") == "boom"

    # Attempt 2: retry_count 1 -> 2, still inbox
    executor.process_inbox()
    post = frontmatter.load(source_path)
    assert post.get("status") == "inbox"
    assert int(post.get("retry_count") or 0) == 2

    # Attempt 3: retry_count already at max (2) -> fetch_failed
    executor.process_inbox()
    post = frontmatter.load(source_path)
    assert post.get("status") == "fetch_failed"

    # retry_failed flips it back to inbox and clears retry_count
    n = executor.retry_failed()
    assert n == 1
    post = frontmatter.load(source_path)
    assert post.get("status") == "inbox"
    assert "retry_count" not in post.metadata
