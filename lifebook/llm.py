"""LLM client wrapper (Anthropic Messages API).

Provides `structured_call`, `text_call`, and `agentic_call` helpers
for structured output, plain text generation, and multi-turn tool use.
"""
from __future__ import annotations

import logging
import random
import re
import time
from typing import Any, TYPE_CHECKING

import anthropic
import httpx

from .config import LLMConfig

if TYPE_CHECKING:
    from .image_processor import ImageData

logger = logging.getLogger(__name__)

_TRANSIENT_ERRORS = (
    anthropic.APIConnectionError,
    anthropic.RateLimitError,
    anthropic.APITimeoutError,
)

# DeepSeek XML tool call format: <｜DSML｜invoke name="xxx"> ... </｜DSML｜invoke>
_DSLM_INVOKE_RE = re.compile(
    r'<｜DSML｜invoke\s+name="([^"]+)">(.*?)</｜DSML｜invoke>',
    re.DOTALL,
)
_DSLM_PARAM_RE = re.compile(
    r'<｜DSML｜parameter\s+name="([^"]+)"[^｜>]*>(.*?)</｜DSML｜parameter>',
    re.DOTALL,
)

def _parse_tool_calls_from_content(content: str) -> list[dict[str, Any]]:
    """Parse tool calls from DeepSeek's XML format in text content."""
    results = []
    for m in _DSLM_INVOKE_RE.finditer(content):
        name = m.group(1)
        params_xml = m.group(2)
        args = {}
        for pm in _DSLM_PARAM_RE.finditer(params_xml):
            args[pm.group(1)] = pm.group(2).strip()
        if name:
            results.append({"name": name, "args": args})
    return results


def _to_anthropic_tool(tool: dict, cache: bool = False) -> dict:
    """Convert provider-agnostic tool dict to Anthropic tool format."""
    result = {
        "name": tool["name"],
        "description": tool["description"],
        "input_schema": tool["input_schema"],
    }
    if cache:
        result["cache_control"] = {"type": "ephemeral"}
    return result


def _parse_response(response) -> tuple[list[dict[str, Any]], str]:
    """Single-pass extraction of tool_use blocks and text from response content."""
    tool_uses = []
    text_parts = []
    for block in response.content:
        if block.type == "tool_use":
            tool_uses.append({
                "id": block.id,
                "name": block.name,
                "input": block.input,
            })
        elif hasattr(block, "text"):
            text_parts.append(block.text)
    return tool_uses, "".join(text_parts)


class _StripAuthMiddleware(httpx.BaseTransport):
    """Strip Authorization header that the SDK injects from env vars."""
    def __init__(self, transport: httpx.BaseTransport):
        self._transport = transport

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if "authorization" in request.headers:
            del request.headers["authorization"]
        return self._transport.handle_request(request)


class LLMClient:
    def __init__(self, cfg: LLMConfig):
        self.cfg = cfg
        http_client = httpx.Client(
            transport=_StripAuthMiddleware(httpx.HTTPTransport()),
            timeout=cfg.timeout,
        )
        kwargs: dict[str, Any] = {
            "api_key": cfg.api_key,
            "base_url": cfg.base_url,
            "http_client": http_client,
        }
        if cfg.extra_headers:
            kwargs["default_headers"] = cfg.extra_headers
        self.client = anthropic.Anthropic(**kwargs)

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
        images: list[ImageData] | None = None,
    ) -> dict[str, Any]:
        """Force the model to produce structured output via tool_use.

        When ``images`` is provided the user message is sent as a multimodal
        content list (image blocks followed by the text prompt) using the
        Anthropic base64 image format.
        """
        tool = _to_anthropic_tool({
            "name": tool_name,
            "description": tool_description,
            "input_schema": input_schema,
        }, cache=True)
        last_error: str | None = None
        for attempt in range(max_retries + 1):
            if attempt > 0:
                delay = min(2 ** (attempt - 1) + random.random(), 30)
                logger.warning(
                    "structured_call retry %d/%d, sleeping %.1fs",
                    attempt, max_retries, delay,
                )
                time.sleep(delay)

            if images:
                content: Any = [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": img.media_type,
                            "data": img.base64_data,
                        },
                    }
                    for img in images
                ]
                content.append({"type": "text", "text": user_prompt})
            else:
                content = user_prompt

            kwargs: dict[str, Any] = {
                "model": model or self.cfg.model,
                "max_tokens": max_tokens or self.cfg.max_tokens,
                "temperature": self.cfg.temperature,
                "tools": [tool],
                "tool_choice": {"type": "tool", "name": tool_name},
                "messages": [{"role": "user", "content": content}],
            }
            if system:
                kwargs["system"] = [
                    {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}},
                ]

            try:
                response = self.client.messages.create(**kwargs)
            except _TRANSIENT_ERRORS:
                if attempt < max_retries:
                    logger.warning(
                        "structured_call transient error on attempt %d/%d",
                        attempt + 1, max_retries + 1,
                    )
                    continue
                raise

            tool_uses, text_content = _parse_response(response)
            for tu in tool_uses:
                if tu["name"] == tool_name:
                    result = tu["input"]
                    if result:
                        return result
                    last_error = f"empty tool_use input (stop_reason={response.stop_reason})"
                    break
            else:
                # No matching tool_use — check for DSML in text content
                xml_calls = _parse_tool_calls_from_content(text_content)
                for xc in xml_calls:
                    if xc["name"] == tool_name:
                        if xc["args"]:
                            return xc["args"]
                        last_error = "empty XML tool args"
                        break
                else:
                    last_error = (
                        f"no tool_use block (stop_reason={response.stop_reason}, "
                        f"content={text_content[:200]!r})"
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
        max_retries: int = 2,
    ) -> str:
        """Plain text generation."""
        if messages is not None:
            msg_list = list(messages)
        elif user_prompt is not None:
            msg_list = [{"role": "user", "content": user_prompt}]
        else:
            raise ValueError("Either user_prompt or messages must be provided")

        last_error: Exception | None = None
        for attempt in range(max_retries + 1):
            if attempt > 0:
                delay = min(2 ** (attempt - 1) + random.random(), 30)
                logger.warning(
                    "text_call retry %d/%d, sleeping %.1fs",
                    attempt, max_retries, delay,
                )
                time.sleep(delay)

            kwargs: dict[str, Any] = {
                "model": model or self.cfg.model,
                "max_tokens": max_tokens or self.cfg.max_tokens,
                "temperature": self.cfg.temperature,
                "messages": msg_list,
            }
            if system:
                kwargs["system"] = [
                    {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}},
                ]

            try:
                response = self.client.messages.create(**kwargs)
            except _TRANSIENT_ERRORS as exc:
                last_error = exc
                if attempt < max_retries:
                    logger.warning(
                        "text_call transient error on attempt %d/%d",
                        attempt + 1, max_retries + 1,
                    )
                    continue
                raise

            _, text_content = _parse_response(response)
            return text_content.strip()

        raise last_error  # type: ignore[misc]

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
        anthropic_tools = [_to_anthropic_tool(t, cache=(i == len(tools) - 1))
                           for i, t in enumerate(tools)]
        tool_names = {t["name"] for t in tools}
        msgs: list[dict[str, Any]] = list(messages)
        cached_system = [
            {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}},
        ]

        for _round in range(max_rounds):
            kwargs: dict[str, Any] = {
                "model": model or self.cfg.model,
                "max_tokens": max_tokens or self.cfg.max_tokens,
                "temperature": self.cfg.temperature,
                "system": cached_system,
                "messages": msgs,
                "tools": anthropic_tools,
            }

            response = self._call_with_retry(kwargs)

            tool_uses, text_content = _parse_response(response)

            if not tool_uses:
                # No tool_use blocks — check for DSML in text content
                logger.info("agentic_call: no tool_use blocks, content=%r", text_content[:300])
                parsed = _parse_tool_calls_from_content(text_content)

                if not parsed:
                    return text_content.strip()

                # Execute tools and inject results as a user message
                tool_results_text = []
                for xc in parsed:
                    if xc["name"] in tool_names:
                        executor = tool_executor.get(xc["name"])
                        if executor:
                            result_str = executor(xc["args"])
                        else:
                            result_str = f"Unknown tool: {xc['name']}"
                            logger.warning("Unknown tool requested: %s", xc["name"])
                        tool_results_text.append(f"[{xc['name']} result]: {result_str}")

                msgs.append({"role": "user", "content": "\n\n".join(tool_results_text)})
                continue

            logger.info("agentic_call: executing %d tool calls: %s", len(tool_uses), [tu["name"] for tu in tool_uses])

            # Append assistant message with tool_use blocks
            assistant_content = []
            if text_content:
                assistant_content.append({"type": "text", "text": text_content})
            for tu in tool_uses:
                assistant_content.append({
                    "type": "tool_use",
                    "id": tu["id"],
                    "name": tu["name"],
                    "input": tu["input"],
                })
            msgs.append({"role": "assistant", "content": assistant_content})

            # Execute tools and append results
            tool_results = []
            for tu in tool_uses:
                executor = tool_executor.get(tu["name"])
                if executor:
                    result_str = executor(tu["input"])
                else:
                    result_str = f"Unknown tool: {tu['name']}"
                    logger.warning("Unknown tool requested: %s", tu["name"])
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu["id"],
                    "content": result_str,
                })
            msgs.append({"role": "user", "content": tool_results})

        # max_rounds exceeded — force a text response without tools
        fallback_kwargs: dict[str, Any] = {
            "model": model or self.cfg.model,
            "max_tokens": max_tokens or self.cfg.max_tokens,
            "temperature": self.cfg.temperature,
            "system": cached_system,
            "messages": msgs + [{"role": "user", "content": "请用文字回复，不要再调用工具。"}],
        }
        response = self._call_with_retry(fallback_kwargs)
        _, final = _parse_response(response)
        final = final.strip()
        final = _DSLM_INVOKE_RE.sub("", final)
        return final.strip()

    def _call_with_retry(self, kwargs: dict[str, Any], max_retries: int = 2) -> Any:
        """Call messages.create with retry on transient errors."""
        for attempt in range(max_retries + 1):
            if attempt > 0:
                delay = min(2 ** (attempt - 1) + random.random(), 30)
                logger.warning(
                    "agentic_call retry %d/%d, sleeping %.1fs",
                    attempt, max_retries, delay,
                )
                time.sleep(delay)
            try:
                return self.client.messages.create(**kwargs)
            except _TRANSIENT_ERRORS:
                if attempt < max_retries:
                    logger.warning(
                        "agentic_call transient error on attempt %d/%d",
                        attempt + 1, max_retries + 1,
                    )
                    continue
                raise
