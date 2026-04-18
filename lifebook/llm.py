"""LLM client wrapper (Anthropic-compatible API).

Provides a `structured_call` helper that uses tool_use (function calling)
to reliably extract structured output from the model.
"""
from __future__ import annotations

import logging
from typing import Any

from anthropic import Anthropic

from .config import LLMConfig

logger = logging.getLogger(__name__)


class LLMClient:
    def __init__(self, cfg: LLMConfig):
        self.cfg = cfg
        # Defeat env-var pollution from ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN
        # by explicitly pinning the Authorization Bearer header. default_headers
        # override the SDK's auto-injected auth headers.
        headers = {
            "Authorization": f"Bearer {cfg.api_key}",
            "x-api-key": cfg.api_key,  # some Anthropic-compatible endpoints use this
        }
        if cfg.extra_headers:
            headers.update(cfg.extra_headers)
        self.client = Anthropic(
            api_key=cfg.api_key,
            base_url=cfg.base_url,
            default_headers=headers,
            timeout=cfg.timeout,
        )

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
    ) -> dict[str, Any]:
        """Force the model to produce structured output via tool_use.

        Returns the tool input dict. Retries once on empty tool_use input
        (some providers occasionally emit empty blocks under load).
        Raises RuntimeError after max_retries if no valid tool_use block.
        """
        tool = {
            "name": tool_name,
            "description": tool_description,
            "input_schema": input_schema,
        }
        last_error: str | None = None
        for attempt in range(max_retries + 1):
            kwargs: dict[str, Any] = {
                "model": model or self.cfg.model,
                "max_tokens": max_tokens or self.cfg.max_tokens,
                "temperature": self.cfg.temperature,
                "tools": [tool],
                "tool_choice": {"type": "tool", "name": tool_name},
                "messages": [{"role": "user", "content": user_prompt}],
            }
            if system:
                kwargs["system"] = system

            resp = self.client.messages.create(**kwargs)
            result: dict[str, Any] | None = None
            for block in resp.content:
                if getattr(block, "type", None) == "tool_use" and block.name == tool_name:
                    result = dict(block.input)
                    break

            if result is None:
                last_error = (
                    f"no tool_use block (stop_reason={resp.stop_reason}, "
                    f"blocks={[getattr(b, 'type', None) for b in resp.content]})"
                )
            elif not result:
                last_error = f"empty tool_use input (stop_reason={resp.stop_reason})"
            else:
                return result

            logger.warning(
                "structured_call attempt %d/%d failed: %s",
                attempt + 1, max_retries + 1, last_error,
            )

        raise RuntimeError(f"LLM structured_call failed after {max_retries + 1} attempts: {last_error}")

    def text_call(
        self,
        user_prompt: str | None = None,
        system: str | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        messages: list[dict[str, str]] | None = None,
    ) -> str:
        """Plain text generation (for digest writing, etc.).

        Either pass user_prompt (single turn) or messages (multi-turn).
        """
        if messages is not None:
            msg_list = messages
        elif user_prompt is not None:
            msg_list = [{"role": "user", "content": user_prompt}]
        else:
            raise ValueError("Either user_prompt or messages must be provided")

        kwargs: dict[str, Any] = {
            "model": model or self.cfg.model,
            "max_tokens": max_tokens or self.cfg.max_tokens,
            "temperature": self.cfg.temperature,
            "messages": msg_list,
        }
        if system:
            kwargs["system"] = system

        resp = self.client.messages.create(**kwargs)
        parts = [getattr(b, "text", "") for b in resp.content if getattr(b, "type", None) == "text"]
        return "".join(parts).strip()
