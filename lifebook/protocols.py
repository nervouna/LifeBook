"""Protocol definitions for dependency injection and testing."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

import frontmatter


class LLMProtocol(Protocol):
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
    ) -> dict[str, Any]: ...

    def text_call(
        self,
        user_prompt: str | None = None,
        system: str | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        messages: list[dict[str, str]] | None = None,
    ) -> str: ...

    def agentic_call(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict],
        tool_executor: dict[str, Any],
        model: str | None = None,
        max_tokens: int | None = None,
        max_rounds: int = 3,
    ) -> str: ...


class FetcherProtocol(Protocol):
    def fetch(self, url: str) -> Any: ...


class StoreProtocol(Protocol):
    def scan_inbox(self) -> list[Path]: ...
    def claim_for_processing(self, source_path: Path) -> tuple[bool, frontmatter.Post]: ...
    def recover_stale(self, timeout_minutes: int = 10, dry_run: bool = False) -> list[tuple[Path, str]]: ...
    def existing_categories(self) -> list[str]: ...
    def find_by_source_url(self, url: str) -> Path | None: ...
    def find_related(self, keywords: list[str], max_hits: int = 5) -> list[str]: ...
    def find_by_title(self, title: str) -> Path | None: ...
    def topic_count(self) -> int: ...
    def search_topics(self, query: str, max_notes: int = 5) -> list[Any]: ...
    def search_topics_formatted(self, query: str, max_notes: int = 5) -> str: ...
    def read_note(self, path: Path) -> frontmatter.Post: ...
    def write_note(self, path: Path, post: frontmatter.Post) -> None: ...
