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
        raise AssertionError(
            f"FakeFetcher: no scripted response for {url!r}. "
            f"Use fetcher.script(url, FetchResult(...)) before invoking."
        )


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


def fake_fetch_result(
    url: str,
    *,
    ok: bool = True,
    content: str = "",
    title: str | None = None,
    via: str = "fake",
    error: str | None = None,
    status: str | None = None,
) -> FetchResult:
    """Convenience factory that fills in FetchResult's required fields.

    `lifebook.fetcher.FetchResult` requires `status` and `url` positionally;
    callers usually want a sensible default (`"ok"` for success / `"fetch_failed"`
    for failure) so this factory provides them.
    """
    if status is None:
        status = "ok" if ok else "fetch_failed"
    return FetchResult(
        ok=ok,
        status=status,
        url=url,
        content=content,
        title=title,
        via=via,
        error=error,
    )
