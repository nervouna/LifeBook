"""LLM client wrapper (OpenAI-compatible API).

Provides `structured_call`, `text_call`, and `agentic_call` helpers
for structured output, plain text generation, and multi-turn tool use.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from openai import OpenAI

from .config import LLMConfig

logger = logging.getLogger(__name__)


def _to_openai_tool(tool: dict) -> dict:
    """Convert provider-agnostic tool dict to OpenAI function-calling format."""
    return {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool["description"],
            "parameters": tool["input_schema"],
        },
    }


class LLMClient:
    def __init__(self, cfg: LLMConfig):
        self.cfg = cfg
        kwargs: dict[str, Any] = {
            "api_key": cfg.api_key,
            "base_url": cfg.base_url,
            "timeout": cfg.timeout,
        }
        if cfg.extra_headers:
            kwargs["default_headers"] = cfg.extra_headers
        self.client = OpenAI(**kwargs)

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

        Returns the tool input dict. Retries on empty tool_use input.
        Raises RuntimeError after max_retries if no valid tool_use block.
        """
        tool = _to_openai_tool({
            "name": tool_name,
            "description": tool_description,
            "input_schema": input_schema,
        })
        last_error: str | None = None
        for attempt in range(max_retries + 1):
            messages: list[dict[str, Any]] = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": user_prompt})

            resp = self.client.chat.completions.create(
                model=model or self.cfg.model,
                max_tokens=max_tokens or self.cfg.max_tokens,
                temperature=self.cfg.temperature,
                tools=[tool],
                tool_choice={"type": "function", "function": {"name": tool_name}},
                messages=messages,
            )
            msg = resp.choices[0].message
            if msg.tool_calls:
                for tc in msg.tool_calls:
                    if tc.function.name == tool_name:
                        result = json.loads(tc.function.arguments)
                        if result:
                            return result
                        last_error = f"empty tool_use input (finish_reason={resp.choices[0].finish_reason})"
                        break
                else:
                    last_error = f"no matching tool call for {tool_name}"
            else:
                last_error = (
                    f"no tool_calls (finish_reason={resp.choices[0].finish_reason}, "
                    f"content={msg.content!r})"
                )

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
        """Plain text generation (for digest writing, etc.)."""
        if messages is not None:
            msg_list = list(messages)
        elif user_prompt is not None:
            msg_list = [{"role": "user", "content": user_prompt}]
        else:
            raise ValueError("Either user_prompt or messages must be provided")

        if system:
            msg_list = [{"role": "system", "content": system}] + msg_list

        resp = self.client.chat.completions.create(
            model=model or self.cfg.model,
            max_tokens=max_tokens or self.cfg.max_tokens,
            temperature=self.cfg.temperature,
            messages=msg_list,
        )
        return (resp.choices[0].message.content or "").strip()

    def agentic_call(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict],
        tool_executor: dict[str, callable],
        model: str | None = None,
        max_tokens: int | None = None,
        max_rounds: int = 3,
    ) -> str:
        """Multi-turn tool-use loop. Returns final text response."""
        openai_tools = [_to_openai_tool(t) for t in tools]
        msgs: list[dict[str, Any]] = [{"role": "system", "content": system}] + list(messages)

        for _round in range(max_rounds):
            resp = self.client.chat.completions.create(
                model=model or self.cfg.model,
                max_tokens=max_tokens or self.cfg.max_tokens,
                temperature=self.cfg.temperature,
                messages=msgs,
                tools=openai_tools,
                tool_choice="auto",
            )
            msg = resp.choices[0].message

            if not msg.tool_calls:
                return (msg.content or "").strip()

            # Append assistant message with tool calls
            assistant_msg: dict[str, Any] = {"role": "assistant", "content": msg.content or ""}
            assistant_msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in msg.tool_calls
            ]
            msgs.append(assistant_msg)

            # Execute tools and append results
            for tc in msg.tool_calls:
                executor = tool_executor.get(tc.function.name)
                if executor:
                    args = json.loads(tc.function.arguments)
                    result_str = executor(args)
                else:
                    result_str = f"Unknown tool: {tc.function.name}"
                    logger.warning("Unknown tool requested: %s", tc.function.name)
                msgs.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result_str,
                })

        # max_rounds exceeded — final call without tools to force text
        resp = self.client.chat.completions.create(
            model=model or self.cfg.model,
            max_tokens=max_tokens or self.cfg.max_tokens,
            temperature=self.cfg.temperature,
            messages=msgs,
        )
        return (resp.choices[0].message.content or "").strip()
