# 阶段 1：契约测试安全网 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `tests/contract/` 下建立一组**黑盒契约测试**，作为后续 4 个重构阶段的回归基线——锁定 inbox / writer 主链路的当前外部行为，使后续的 services 抽取、writer 拆包、executor 管道化、CLI 重排都能用这一组测试快速发现退化。

**Architecture:** 6 个契约测试文件 + 1 个 contract 专用 conftest。所有用例直接调当前的 `Executor` / `Writer` / `ingest_*` / `NoteStore` 等老接口（**这阶段不引入 services 层**），只断言"外部可观测的行为"——文件落盘、frontmatter 字段、返回 DTO 字段。阶段 2 起把这批测试切换到调 `services/`——**切换那一步本身就是回归证据**。LLM 用一个 `FakeLLMClient`（按入参 `tool_name` / `system` 路由到预设响应），其他全走真实文件系统（`tmp_path`）。

**Tech Stack:** pytest、`tmp_path` fixture、复用 `tests/conftest.py::make_config` 与 `write_source`、纯 dataclass `FakeLLMClient`（无 `unittest.mock` 依赖）。

**Spec 偏离声明:** spec 第 10.1 节列出 6 条契约测试，含 `test_search_after_index.py`（依赖真 ChromaDB + sentence-transformers）。但现有 `tests/conftest.py` 在顶层全局 mock 了 `chromadb` 与 `sentence_transformers`，与"走真实模型"冲突。本 plan 把 `test_search_after_index.py` 替换为 `test_search_keyword.py`（基于 `NoteStore.search_topics` 关键词检索），真 ChromaDB 契约测试推迟到阶段 2 一起补——届时 services 抽出后可在 `tests/contract/conftest.py` 局部 unmock。范围共 5 条用例。

---

## 文件结构

新增（不修改任何业务代码）：
```
tests/contract/
├── __init__.py                  # 空，仅让 tests/contract/ 成为可导入包
├── _helpers.py                  # FakeLLMClient + FakeFetcher + extract_payload（普通模块，可 import）
├── conftest.py                  # 仅 fixture（cfg / fake_llm / fake_fetcher / make_executor / make_writer）
├── test_inbox_lifecycle.py      # ingest_url → executor.process_inbox → 笔记落盘
├── test_inbox_recovery.py       # processing 状态超时 → recover_stale → 复 process
├── test_inbox_retry.py          # fetch 失败累加 → retry_count → fetch_failed → retry → 重新 inbox
├── test_search_keyword.py       # process 后通过 NoteStore.search_topics 命中
├── test_writer_lifecycle.py     # Writer.start → continue → publish → 99-publish/ 落盘
└── test_writer_restore.py       # 写到一半 → restore → draft 还原
```

> **设计要点：** `conftest.py` 只放 fixture，不放被测试 import 的 helpers——pytest 把 conftest 当成 hook 加载，业务/测试代码直接 `import` conftest 在某些 pytest 版本下会出问题。所有"非 fixture 的可复用代码"都放到 `_helpers.py`，从那里 import。

---

## Task 1：建 contract 目录与 FakeLLMClient

**Files:**
- Create: `tests/contract/__init__.py`
- Create: `tests/contract/_helpers.py`
- Create: `tests/contract/conftest.py`

`FakeLLMClient` 必须能替换 `LLMClient`，被 `Executor`、`Writer` 以 duck-typing 方式调用。它需要实现 3 个方法：`structured_call(...)`、`text_call(...)`、`agentic_call(...)`，签名见 `lifebook/llm.py:109,212,267`。

设计：用一个先入先出队列存预设响应；调用时严格按顺序消费，不匹配 `tool_name` 直接 raise（避免"忘了 queue → 拿到默认值 → 测试看似过了"的暗坑）。

- [ ] **Step 1: 写 `tests/contract/__init__.py`**

一个空文件，让 `tests/contract/` 成为可导入的 Python 包（测试文件中 `from ._helpers import ...` 才能工作）。

- [ ] **Step 2: 写 `tests/contract/_helpers.py`**

```python
"""契约测试的纯 Python helpers — FakeLLMClient / FakeFetcher / extract_payload。

放在普通模块而不是 conftest.py：conftest 是 pytest 内部加载的 hook 文件，
不应被业务/测试代码直接 import。
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable

from lifebook.fetcher import FetchResult


# --------- FakeLLMClient ---------

@dataclass
class _StructuredResponse:
    tool_name: str
    payload: dict[str, Any]


@dataclass
class FakeLLMClient:
    """Minimal stand-in for LLMClient. Records calls; returns scripted answers.

    Usage:
        llm = FakeLLMClient()
        llm.queue_structured("extract_note", {...})
        llm.queue_text("hello")
    """

    structured_queue: deque[_StructuredResponse] = field(default_factory=deque)
    text_queue: deque[str] = field(default_factory=deque)
    agentic_queue: deque[str] = field(default_factory=deque)
    structured_calls: list[dict[str, Any]] = field(default_factory=list)
    text_calls: list[dict[str, Any]] = field(default_factory=list)
    agentic_calls: list[dict[str, Any]] = field(default_factory=list)

    # ---- queueing helpers ----
    def queue_structured(self, tool_name: str, payload: dict[str, Any]) -> None:
        self.structured_queue.append(_StructuredResponse(tool_name, payload))

    def queue_text(self, text: str) -> None:
        self.text_queue.append(text)

    def queue_agentic(self, text: str) -> None:
        self.agentic_queue.append(text)

    # ---- duck-typed LLMClient API ----
    def structured_call(
        self,
        tool_name: str,
        tool_description: str,
        input_schema: dict[str, Any],
        user_prompt: str,
        system: str | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        max_retries: int = 2,
        images: Any = None,
    ) -> dict[str, Any]:
        self.structured_calls.append({
            "tool_name": tool_name,
            "user_prompt": user_prompt,
            "system": system,
            "images": images,
        })
        if not self.structured_queue:
            raise AssertionError(
                f"FakeLLMClient: no scripted response for structured_call(tool_name={tool_name!r}). "
                f"Use llm.queue_structured(...) before invoking."
            )
        head = self.structured_queue[0]
        if head.tool_name != tool_name:
            raise AssertionError(
                f"FakeLLMClient: queued structured response for {head.tool_name!r}, "
                f"got call for {tool_name!r}"
            )
        self.structured_queue.popleft()
        return dict(head.payload)

    def text_call(
        self,
        user_prompt: str | None = None,
        system: str | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        messages: list[dict[str, str]] | None = None,
        max_retries: int = 2,
    ) -> str:
        self.text_calls.append({
            "user_prompt": user_prompt,
            "system": system,
            "messages": messages,
        })
        if not self.text_queue:
            raise AssertionError(
                "FakeLLMClient: no scripted response for text_call(). "
                "Use llm.queue_text(...) before invoking."
            )
        return self.text_queue.popleft()

    def agentic_call(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict],
        tool_executor: dict[str, Callable],
        model: str | None = None,
        max_tokens: int | None = None,
        max_rounds: int = 3,
    ) -> str:
        self.agentic_calls.append({
            "system": system,
            "messages": list(messages),
            "tool_names": [t["name"] for t in tools],
        })
        if not self.agentic_queue:
            raise AssertionError(
                "FakeLLMClient: no scripted response for agentic_call(). "
                "Use llm.queue_agentic(...) before invoking."
            )
        return self.agentic_queue.popleft()


# --------- Fake Fetcher ---------

@dataclass
class FakeFetcher:
    """Stand-in for Fetcher. Returns scripted FetchResult per URL."""

    plan: dict[str, FetchResult] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    def script(self, url: str, result: FetchResult) -> None:
        self.plan[url] = result

    def fetch(self, url: str) -> FetchResult:
        self.calls.append(url)
        if url in self.plan:
            return self.plan[url]
        return FetchResult(ok=False, status="UNSCRIPTED", error=f"no scripted response for {url}")


# --------- Sample LLM payload helpers ---------

def extract_payload(
    *,
    title: str = "测试笔记",
    summary: str = "这是摘要。",
    key_points: list[str] | None = None,
    narrative: str = "正文内容。",
    category: str = "AI技术",
    tags: list[str] | None = None,
    related_keywords: list[str] | None = None,
    confidence: float = 0.9,
) -> dict[str, Any]:
    """Build a payload that matches build_extract_tool_schema's expected shape."""
    return {
        "title": title,
        "summary": summary,
        "key_points": key_points or ["要点1", "要点2"],
        "narrative": narrative,
        "category": category,
        "tags": tags or ["llm"],
        "related_keywords": related_keywords or ["人工智能"],
        "confidence": confidence,
    }
```

- [ ] **Step 3: 写 `tests/contract/conftest.py`**

```python
"""契约测试层 fixtures。LLM 全 fake，其余（文件系统、frontmatter、Executor）走真实路径。

注：顶层 tests/conftest.py 已经全局 mock 了 chromadb / sentence_transformers，此处无需再 mock。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from lifebook.config import (
    Config, KnowledgeConfig, LLMConfig, FeishuConfig,
    ExecutorConfig, DigestConfig, TavilyConfig, FetchConfig, LoggingConfig,
)
from lifebook.executor import Executor
from lifebook.writer import Writer

from ._helpers import FakeFetcher, FakeLLMClient


def _make_config(tmp_path: Path) -> Config:
    """Real Config rooted at tmp_path."""
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "10-sources").mkdir()
    (kb / "20-topics").mkdir()
    (kb / "30-trajectories").mkdir()
    (kb / "99-publish").mkdir()
    (kb / ".lifebook").mkdir()
    return Config(
        knowledge=KnowledgeConfig(root=kb),
        llm=LLMConfig(),
        feishu=FeishuConfig(),
        executor=ExecutorConfig(),
        digest=DigestConfig(),
        tavily=TavilyConfig(),
        fetch=FetchConfig(),
        logging=LoggingConfig(),
    )


# --------- Fixtures ---------

@pytest.fixture
def cfg(tmp_path: Path):
    """Real Config rooted at tmp_path. Categories include those used in tests."""
    config = _make_config(tmp_path)
    # 缩短 fetch 重试上限以便 retry 测试更快
    config.executor.max_retries = 2
    config.executor.processing_delay = 0
    config.executor.max_workers = 1  # serialize for deterministic assertions
    return config


@pytest.fixture
def fake_llm():
    return FakeLLMClient()


@pytest.fixture
def fake_fetcher():
    return FakeFetcher()


@pytest.fixture
def make_executor(cfg, fake_llm, fake_fetcher):
    """Build an Executor wired with fakes."""
    def _build():
        return Executor(cfg=cfg, llm=fake_llm, fetcher=fake_fetcher)
    return _build


@pytest.fixture
def make_writer(cfg, fake_llm):
    """Build a Writer wired with the fake LLM."""
    def _build():
        return Writer(cfg=cfg, llm=fake_llm)
    return _build
```

- [ ] **Step 4: 跑一下让 pytest 发现并能 import 这个 conftest**

Run: `pytest tests/contract --collect-only -q`
Expected: 没有 import 错误；输出形如 `0 tests collected`（因为 test_*.py 还没写）。

- [ ] **Step 5: Commit**

```bash
git add tests/contract/__init__.py tests/contract/_helpers.py tests/contract/conftest.py
git commit -m "test: add contract test scaffolding (FakeLLMClient + fixtures)"
```

---

## Task 2：`test_inbox_lifecycle.py` —— ingest URL → process → 笔记落盘

**Files:**
- Create: `tests/contract/test_inbox_lifecycle.py`

锁定的契约：
1. `ingest_url(...)` 在 `10-sources/` 写入一份 `status: inbox` 的 .md
2. `Executor.process_inbox()` 读取后，借 `Fetcher.fetch` 拿到内容、调 `LLMClient.structured_call` 提取
3. 成功后：源文件 `status` 变 `processed`、`topic_ref` 指向新 topic 文件；topic 文件落到 `20-topics/<category>/<slug>.md`，frontmatter 含 `title`、`category`、`tags`

- [ ] **Step 1: 写测试**

```python
"""契约：URL 录入 → 处理 → topic 落盘 全链路。

锁定外部行为：源文件状态机、topic 文件路径与 frontmatter 关键字段。
"""
from __future__ import annotations

import frontmatter

from lifebook.fetcher import FetchResult
from lifebook.ingest import ingest_url

from ._helpers import extract_payload


def test_url_ingest_then_process_writes_topic(cfg, make_executor, fake_fetcher, fake_llm):
    # 1) ingest a URL — should land in 10-sources as status:inbox with empty body
    url = "https://example.com/article"
    source_path = ingest_url(cfg.knowledge, url, title_hint="示例文章")
    assert source_path.parent == cfg.knowledge.sources_path
    src_post = frontmatter.load(source_path)
    assert src_post.get("status") == "inbox"
    assert src_post.get("source") == url

    # 2) script the fetcher and the LLM
    fake_fetcher.script(url, FetchResult(
        ok=True,
        content="一段被抓取下来的正文，谈论人工智能的进展。",
        title="示例文章",
        via="fake",
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
    assert "这是摘要" in topic_post.content or "摘要" in topic_post.content
```

- [ ] **Step 2: 跑测试**

Run: `pytest tests/contract/test_inbox_lifecycle.py -v`
Expected: PASS（一个用例通过）。如果 FAIL，**不要**马上改测试——读 `r.error` 与 frontmatter 内容，先理解原因；多数情况是 fake 配置不够（如某个分类不在默认 categories 里），回到 conftest 修 helper，不要降低断言强度。

- [ ] **Step 3: Commit**

```bash
git add tests/contract/test_inbox_lifecycle.py
git commit -m "test: contract — url ingest → process → topic write"
```

---

## Task 3：`test_inbox_recovery.py` —— processing 卡死的恢复

**Files:**
- Create: `tests/contract/test_inbox_recovery.py`

锁定的契约：
- 一份 `status: processing` 且 `processing_at` 早于 `timeout_minutes` 的源文件，被 `Executor.recover_stale(timeout_minutes=...)` 翻回 `inbox`、清掉 `processing_at`
- 翻回后，再 `process_inbox()` 能成功

- [ ] **Step 1: 写测试**

```python
"""契约：processing 状态超时 → recover_stale → 重新 process 成功。"""
from __future__ import annotations

from datetime import datetime, timedelta

import frontmatter

from lifebook.fetcher import FetchResult
from lifebook.notes import CN_TZ, write_note, new_post

from ._helpers import extract_payload


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
    fake_fetcher.script("https://example.com/stuck", FetchResult(
        ok=True, content="recovered content body", title="Recovered", via="fake",
    ))
    fake_llm.queue_structured("extract_note", extract_payload(title="Recovered"))

    results = executor.process_inbox()
    assert len(results) == 1 and results[0].ok, f"recovery roundtrip failed: {results[0].error}"
    assert frontmatter.load(path).get("status") == "processed"
```

- [ ] **Step 2: 跑测试**

Run: `pytest tests/contract/test_inbox_recovery.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/contract/test_inbox_recovery.py
git commit -m "test: contract — recover stale processing then re-process"
```

---

## Task 4：`test_inbox_retry.py` —— fetch 失败的 retry 阶梯

**Files:**
- Create: `tests/contract/test_inbox_retry.py`

锁定的契约（参 `executor._fetch_if_needed` 行为）：
1. 第一次 fetch 失败 → 源文件回到 `status: inbox`、`retry_count = 1`
2. 重复直到 `retry_count == max_retries`（conftest 中设为 2）
3. 再失败一次 → 源文件 `status: fetch_failed`
4. `Executor.retry_failed()` 把 `fetch_failed` 重置为 `inbox`、清 `retry_count`

- [ ] **Step 1: 写测试**

```python
"""契约：fetch 失败的退避与最终 fetch_failed 状态、以及 retry_failed 的复位。"""
from __future__ import annotations

import frontmatter

from lifebook.fetcher import FetchResult
from lifebook.ingest import ingest_url


def test_fetch_failure_increments_retry_then_fails_then_retried(cfg, make_executor, fake_fetcher):
    url = "https://example.com/broken"
    source_path = ingest_url(cfg.knowledge, url)

    # All fetches fail
    fake_fetcher.script(url, FetchResult(ok=False, status="ERR", error="boom"))

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
    assert post.get("retry_count") is None or "retry_count" not in post.metadata
```

- [ ] **Step 2: 跑测试**

Run: `pytest tests/contract/test_inbox_retry.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/contract/test_inbox_retry.py
git commit -m "test: contract — fetch retry ladder and retry_failed reset"
```

---

## Task 5：`test_search_keyword.py` —— process 后能被 `search_topics` 命中

**Files:**
- Create: `tests/contract/test_search_keyword.py`

替代 spec 中的 `test_search_after_index.py`（详见 plan 顶部的偏离声明）。验证 `NoteStore.search_topics`（关键词 + 结构化字段打分）的契约：经过 process 后写入的 topic，应该可以被相关关键词检索到。

- [ ] **Step 1: 写测试**

```python
"""契约：process 后的 topic 可被 NoteStore.search_topics 命中（关键词层）。

真 ChromaDB 契约推迟到阶段 2（届时 services 抽出后局部 unmock）。
"""
from __future__ import annotations

from lifebook.fetcher import FetchResult
from lifebook.ingest import ingest_url
from lifebook.store import NoteStore

from ._helpers import extract_payload


def test_processed_topic_is_searchable_by_keyword(cfg, make_executor, fake_fetcher, fake_llm):
    url = "https://example.com/transformer"
    ingest_url(cfg.knowledge, url, title_hint="Transformer 架构")

    fake_fetcher.script(url, FetchResult(
        ok=True,
        content="深入讲解 Transformer 架构。",
        title="Transformer 架构",
        via="fake",
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
```

- [ ] **Step 2: 跑测试**

Run: `pytest tests/contract/test_search_keyword.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/contract/test_search_keyword.py
git commit -m "test: contract — keyword search hits processed topic"
```

---

## Task 6：`test_writer_lifecycle.py` —— Writer.start → publish

**Files:**
- Create: `tests/contract/test_writer_lifecycle.py`

锁定的契约：
- `Writer.start(idea)` 创建 `draft.md` + `draft.json`，使 `writer.active is True`，stage 为 `concept`
- `Writer.publish()` 把当前 `draft.md` 内容发布到 `99-publish/<slug>.md`、清空 draft 文件

> 备注：`Writer` 的 `_vector_search` 在没有真实 vector index 时会自动降级到 `NoteStore.search_topics`（参 `writer.py:70-87`）。顶层 conftest 的 chromadb mock 不会拦它——`VectorIndex` 构造可能在 mock 模块下抛 `Exception`，触发 `except` 分支。这是预期行为，测试不需要额外干预。

- [ ] **Step 1: 写测试**

```python
"""契约：Writer 的 start → publish 主链路。

锁定 draft 三件套的存在/消失、publish 落盘到 99-publish/。
不验证 LLM 输出的语义、不验证 prompt 内容。
"""
from __future__ import annotations

import json


def test_writer_start_creates_draft_then_publish_writes_file(cfg, make_writer, fake_llm):
    writer = make_writer()
    assert writer.active is False, "no active draft expected at start of test"

    # Stage 1: start — produces concept via structured_call
    fake_llm.queue_structured("generate_concept", {
        "title": "我的第一篇文章",
        "concept": "讲讲 LifeBook 的设计哲学。",
        "key_points": ["要点A", "要点B"],
        "tags": ["设计", "工程"],
        "category": "AI技术",
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
    assert meta.get("title") == "我的第一篇文章"

    # Force-advance to a publishable state by writing draft body and flipping stage.
    # Goal here is to lock the publish contract, not the multi-stage path.
    writer.draft_path.write_text(
        "# 我的第一篇文章\n\n这是文章正文，要够长以便发布通过。\n", encoding="utf-8"
    )
    meta["stage"] = "review"
    writer.draft_meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")

    published_path = writer.publish()
    assert published_path is not None
    assert published_path.is_relative_to(cfg.knowledge.publish_path)
    assert published_path.exists()
    # After publish, draft files should be gone (or at least draft.json is gone)
    assert not writer.draft_meta_path.exists(), "draft.json should be cleared after publish"
    assert writer.active is False
```

- [ ] **Step 2: 跑测试**

Run: `pytest tests/contract/test_writer_lifecycle.py -v`
Expected: PASS。

> **如果 FAIL：** 最常见原因是 `Writer.publish()` 的实际签名 / 行为与上面假设不同（例如返回 `str` 提示而非 `Path`，或对 stage 校验更严格）。先 `Read lifebook/writer.py` 找到 `publish` 方法和它的真实返回，再调整测试断言（保留"draft 消失 + 99-publish/ 有文件"两条核心断言；`published_path` 的类型可放宽到 `Path | str` 并按需求探测）。**不要**改 Writer 代码——契约测试是来记录现有行为的，不是改它的。

- [ ] **Step 3: Commit**

```bash
git add tests/contract/test_writer_lifecycle.py
git commit -m "test: contract — writer start → publish lifecycle"
```

---

## Task 7：`test_writer_restore.py` —— 备份与恢复

**Files:**
- Create: `tests/contract/test_writer_restore.py`

锁定的契约：
- 在 draft 存在时调用 `Writer.start(...)` 不应覆盖现有 draft（应返回提示信息，参 `writer.py:110-111`）
- `Writer.restore()` / `Writer.restore_published()` 任一存在的恢复入口：备份目录中的内容能被还原成新的 draft

> 备注：`writer.py` 的实际 `restore` API 需要在写测试前先 `Read` 一次确认（公开方法名、签名、备份目录路径常量）。下面的测试以"提供备份目录里的 draft.json + draft.md → 调 restore → draft 三件套出现"作为最小契约，对具体方法名留了占位注释要求执行者确认。

- [ ] **Step 1: 先 Read 当前 writer.py 的恢复 API**

阅读 `lifebook/writer.py` 中名为 `restore` / `restore_published` / `_backup` 的方法，记录：
1. 备份目录路径（通常在 `publish_path` 下）
2. `restore(...)` 的入参签名（是否接受 `index` 或 `name`）
3. `restore` 失败 / 成功的返回类型

把这三项写到测试文件顶部的注释里，再继续。

- [ ] **Step 2: 写测试**

```python
"""契约：写到一半 → restore 还原。

start 已存在 draft 时返回提示而不覆盖；restore 能从备份恢复。
"""
from __future__ import annotations

import json
from pathlib import Path


def test_start_does_not_overwrite_existing_draft(cfg, make_writer, fake_llm):
    writer = make_writer()

    fake_llm.queue_structured("generate_concept", {
        "title": "已有标题",
        "concept": "已有概念",
        "key_points": ["a"],
        "tags": ["t"],
        "category": "AI技术",
    })
    writer.start("第一篇想法")
    assert writer.active

    original_meta = writer.draft_meta_path.read_text(encoding="utf-8")

    # Calling start again should not consume another LLM call and should
    # return a refusal-style message — NOT overwrite the draft.
    reply = writer.start("第二篇想法")
    assert isinstance(reply, str) and reply.strip()
    # the queued generate_concept must NOT have been popped a second time
    # (we only queued once; if start tried to call LLM again it would have raised)
    assert writer.draft_meta_path.read_text(encoding="utf-8") == original_meta


def test_restore_from_backup(cfg, make_writer):
    """If a backup exists, restore() resurrects draft.md / draft.json.

    Plant a backup directly on disk to avoid coupling the test to Writer's
    internal backup-creating method (whose name may differ across revisions).
    """
    writer = make_writer()
    # Confirm no active draft initially
    assert writer.active is False

    # NOTE: confirm the actual backup directory by reading writer.py before this test.
    # As of the current code, backups live under publish_path/.draft_backups/<timestamp>/.
    backup_dir = cfg.knowledge.publish_path / ".draft_backups" / "20260101-120000"
    backup_dir.mkdir(parents=True)
    (backup_dir / "draft.md").write_text("# 恢复内容\n\n正文。\n", encoding="utf-8")
    (backup_dir / "draft.json").write_text(
        json.dumps({"stage": "content", "title": "恢复内容"}, ensure_ascii=False),
        encoding="utf-8",
    )

    # Call whichever restore entrypoint the Writer exposes. If `restore()`
    # without args resurrects the latest backup, this works; if it requires
    # an index/name, adjust accordingly per Step 1 reading.
    out = writer.restore()
    assert out is not None  # most likely a confirmation string or path

    assert writer.draft_path.exists(), "draft.md should be restored"
    assert writer.draft_meta_path.exists(), "draft.json should be restored"
    meta = json.loads(writer.draft_meta_path.read_text(encoding="utf-8"))
    assert meta.get("title") == "恢复内容"
```

- [ ] **Step 3: 跑测试**

Run: `pytest tests/contract/test_writer_restore.py -v`
Expected: PASS。

> **如果 FAIL：** 多半是备份路径或 `restore` 入参签名与假设不符。回到 Step 1 的 Read 结论，只调测试，不动 Writer。如果发现 `restore` 实际只接受备份名 / 索引，把 fixture 里的备份目录名字调整为 Writer 期望的格式，并补 `restore("20260101-120000")` 之类的调用形式。

- [ ] **Step 4: Commit**

```bash
git add tests/contract/test_writer_restore.py
git commit -m "test: contract — writer start refuses overwrite; restore from backup"
```

---

## Task 8：跑全套契约测试 + 跑全量回归

**Files:** 仅运行命令，无新增。

- [ ] **Step 1: 跑契约层全绿**

Run: `pytest tests/contract -v`
Expected: 5 个文件 / 5+ 个用例全 PASS。

- [ ] **Step 2: 跑全仓回归确认未影响其他测试**

Run: `pytest tests -q`
Expected: 通过。如果有偶发已知失败（与本次新增无关），记录但不在本 plan 范围内修。

- [ ] **Step 3: Commit（如果上面有任何小修补需要落档）**

如果前序步骤里有"修一行 conftest"之类的微调：

```bash
git add -p tests/contract/conftest.py
git commit -m "test: contract — minor scaffolding adjustments after end-to-end run"
```

否则跳过本步骤，直接进入 Step 4。

- [ ] **Step 4: 在 plan 中勾掉所有 task 后，确认阶段 1 完成**

阶段 1 的退出标志（来自 spec 第 11 节）：
- ✅ `pytest tests/contract` 全绿
- ✅ 业务代码未改动（`git diff` 范围只在 `tests/contract/`）

阶段 1 完成后，进入阶段 2（抽 services 层 + AppContext），届时另起一份 plan。

---

## Self-Review Checklist（执行者忽略；编写者用）

**Spec 覆盖：**
- 阶段 1 来自 spec 第 11 节："新增 tests/contract/ 6-8 个用例" → 实际 5 个用例（裁剪 1 个，已在顶部声明）
- 完成标志 "`pytest tests/contract` 全绿" → Task 8 Step 1
- "不改业务代码" → Task 8 Step 4 显式断言 `git diff` 范围

**Placeholder 扫查：** 无 TBD / TODO / "类似上文"。

**类型 / 命名一致性：**
- `FakeLLMClient` 字段名（`structured_queue` 等）在 conftest 与各测试中保持一致。
- `extract_payload(...)` 返回的 key 与 `lifebook/prompts/extract.py::build_extract_tool_schema` 期望的 key 对齐（`title` / `summary` / `key_points` / `narrative` / `category` / `tags` / `related_keywords` / `confidence`）。
- `FetchResult` 的字段名（`ok` / `content` / `title` / `via` / `status` / `error`）来自 `lifebook/fetcher.py`，每个用例使用一致。

**已知风险：**
- Task 6 / 7 涉及 Writer 的 publish / restore 实际 API，测试里给了"如失败的处理建议"，包含必要的 Read-first 步骤。
