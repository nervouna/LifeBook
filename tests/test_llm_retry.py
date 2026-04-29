"""Tests for LLM retry logic, backoff, prompt caching, and TTS 429 retry."""
from __future__ import annotations

import random
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import anthropic
import pytest

from lifebook.config import LLMConfig
from lifebook.llm import LLMClient


def _make_llm():
    cfg = LLMConfig(api_key="fake", base_url="https://fake.api")
    with patch("lifebook.llm.anthropic.Anthropic"):
        client = LLMClient(cfg)
    return client


def _tool_block(name: str, input_data: dict):
    return SimpleNamespace(type="tool_use", id="t1", name=name, input=input_data)


def _text_block(text: str):
    return SimpleNamespace(type="text", text=text)


def _response(blocks, stop_reason="tool_use"):
    return SimpleNamespace(content=blocks, stop_reason=stop_reason)


class TestStructuredCallRetry:
    def test_retries_on_api_connection_error(self):
        llm = _make_llm()
        error = anthropic.APIConnectionError(request=MagicMock())
        ok_resp = _response([_tool_block("extract", {"key": "val"})])
        llm.client.messages.create.side_effect = [error, ok_resp]

        with patch("lifebook.llm.time.sleep"):
            result = llm.structured_call(
                tool_name="extract", tool_description="d",
                input_schema={}, user_prompt="p", max_retries=2,
            )
        assert result == {"key": "val"}
        assert llm.client.messages.create.call_count == 2

    def test_retries_on_rate_limit_error(self):
        llm = _make_llm()
        error = anthropic.RateLimitError(
            message="rate limited",
            response=MagicMock(status_code=429, headers={}),
            body=None,
        )
        ok_resp = _response([_tool_block("extract", {"a": 1})])
        llm.client.messages.create.side_effect = [error, ok_resp]

        with patch("lifebook.llm.time.sleep"):
            result = llm.structured_call(
                tool_name="extract", tool_description="d",
                input_schema={}, user_prompt="p", max_retries=2,
            )
        assert result == {"a": 1}

    def test_retries_on_api_timeout_error(self):
        llm = _make_llm()
        error = anthropic.APITimeoutError(request=MagicMock())
        ok_resp = _response([_tool_block("extract", {"x": 1})])
        llm.client.messages.create.side_effect = [error, ok_resp]

        with patch("lifebook.llm.time.sleep"):
            result = llm.structured_call(
                tool_name="extract", tool_description="d",
                input_schema={}, user_prompt="p", max_retries=2,
            )
        assert result == {"x": 1}

    def test_backoff_before_retry(self):
        llm = _make_llm()
        error = anthropic.APIConnectionError(request=MagicMock())
        ok_resp = _response([_tool_block("extract", {"k": "v"})])
        llm.client.messages.create.side_effect = [error, ok_resp]

        with patch("lifebook.llm.time.sleep") as mock_sleep, \
             patch("lifebook.llm.random.random", return_value=0.5):
            llm.structured_call(
                tool_name="extract", tool_description="d",
                input_schema={}, user_prompt="p", max_retries=2,
            )
        # First retry: delay = min(2^0 + 0.5, 30) = 1.5
        mock_sleep.assert_called_once()
        delay = mock_sleep.call_args[0][0]
        assert 1.0 <= delay <= 2.0

    def test_raises_after_all_retries_exhausted(self):
        llm = _make_llm()
        error = anthropic.APIConnectionError(request=MagicMock())
        llm.client.messages.create.side_effect = error

        with patch("lifebook.llm.time.sleep"):
            with pytest.raises(anthropic.APIConnectionError):
                llm.structured_call(
                    tool_name="extract", tool_description="d",
                    input_schema={}, user_prompt="p", max_retries=2,
                )

    def test_does_not_retry_on_bad_request_error(self):
        llm = _make_llm()
        error = anthropic.BadRequestError(
            message="bad request",
            response=MagicMock(status_code=400, headers={}),
            body=None,
        )
        llm.client.messages.create.side_effect = error

        with pytest.raises(anthropic.BadRequestError):
            llm.structured_call(
                tool_name="extract", tool_description="d",
                input_schema={}, user_prompt="p", max_retries=2,
            )
        assert llm.client.messages.create.call_count == 1


class TestTextCallRetry:
    def test_retries_on_connection_error(self):
        llm = _make_llm()
        error = anthropic.APIConnectionError(request=MagicMock())
        ok_resp = SimpleNamespace(
            content=[_text_block("hello")],
            stop_reason="end_turn",
        )
        llm.client.messages.create.side_effect = [error, ok_resp]

        with patch("lifebook.llm.time.sleep"):
            result = llm.text_call(user_prompt="hi")
        assert result == "hello"
        assert llm.client.messages.create.call_count == 2

    def test_retries_on_timeout_error(self):
        llm = _make_llm()
        error = anthropic.APITimeoutError(request=MagicMock())
        ok_resp = SimpleNamespace(
            content=[_text_block("result")],
            stop_reason="end_turn",
        )
        llm.client.messages.create.side_effect = [error, ok_resp]

        with patch("lifebook.llm.time.sleep"):
            result = llm.text_call(user_prompt="go")
        assert result == "result"

    def test_raises_after_retries_exhausted(self):
        llm = _make_llm()
        error = anthropic.APIConnectionError(request=MagicMock())
        llm.client.messages.create.side_effect = error

        with patch("lifebook.llm.time.sleep"):
            with pytest.raises(anthropic.APIConnectionError):
                llm.text_call(user_prompt="fail")


class TestAgenticCallRetry:
    def test_retries_on_connection_error(self):
        llm = _make_llm()
        error = anthropic.APIConnectionError(request=MagicMock())
        ok_resp = _response([_text_block("done")])
        llm.client.messages.create.side_effect = [error, ok_resp]

        with patch("lifebook.llm.time.sleep"):
            result = llm.agentic_call(
                system="s", messages=[{"role": "user", "content": "hi"}],
                tools=[], tool_executor={},
            )
        assert result == "done"
        assert llm.client.messages.create.call_count == 2

    def test_retries_on_rate_limit_error(self):
        llm = _make_llm()
        error = anthropic.RateLimitError(
            message="rate limited",
            response=MagicMock(status_code=429, headers={}),
            body=None,
        )
        ok_resp = _response([_text_block("ok")])
        llm.client.messages.create.side_effect = [error, ok_resp]

        with patch("lifebook.llm.time.sleep"):
            result = llm.agentic_call(
                system="s", messages=[{"role": "user", "content": "hi"}],
                tools=[], tool_executor={},
            )
        assert result == "ok"

    def test_raises_after_retries_exhausted(self):
        llm = _make_llm()
        error = anthropic.APITimeoutError(request=MagicMock())
        llm.client.messages.create.side_effect = error

        with patch("lifebook.llm.time.sleep"):
            with pytest.raises(anthropic.APITimeoutError):
                llm.agentic_call(
                    system="s", messages=[{"role": "user", "content": "hi"}],
                    tools=[], tool_executor={},
                )


class TestPromptCaching:
    def test_structured_call_uses_cache_control_on_system(self):
        llm = _make_llm()
        llm.client.messages.create.return_value = _response(
            [_tool_block("extract", {"k": "v"})],
        )
        llm.structured_call(
            tool_name="extract", tool_description="d",
            input_schema={}, user_prompt="p", system="system text",
        )
        call_kwargs = llm.client.messages.create.call_args.kwargs
        system = call_kwargs["system"]
        assert isinstance(system, list)
        assert system[0]["cache_control"] == {"type": "ephemeral"}
        assert system[0]["text"] == "system text"

    def test_agentic_call_uses_cache_control_on_system(self):
        llm = _make_llm()
        llm.client.messages.create.return_value = _response(
            [_text_block("done")],
        )
        llm.agentic_call(
            system="sys prompt", messages=[{"role": "user", "content": "hi"}],
            tools=[], tool_executor={},
        )
        call_kwargs = llm.client.messages.create.call_args.kwargs
        system = call_kwargs["system"]
        assert isinstance(system, list)
        assert system[0]["cache_control"] == {"type": "ephemeral"}

    def test_text_call_uses_cache_control_on_system(self):
        llm = _make_llm()
        llm.client.messages.create.return_value = SimpleNamespace(
            content=[_text_block("ok")], stop_reason="end_turn",
        )
        llm.text_call(user_prompt="hi", system="sys text")
        call_kwargs = llm.client.messages.create.call_args.kwargs
        system = call_kwargs["system"]
        assert isinstance(system, list)
        assert system[0]["cache_control"] == {"type": "ephemeral"}

    def test_structured_call_tool_has_cache_control(self):
        llm = _make_llm()
        llm.client.messages.create.return_value = _response(
            [_tool_block("extract", {"k": "v"})],
        )
        llm.structured_call(
            tool_name="extract", tool_description="d",
            input_schema={}, user_prompt="p",
        )
        call_kwargs = llm.client.messages.create.call_args.kwargs
        tools = call_kwargs["tools"]
        assert len(tools) == 1
        assert tools[0]["cache_control"] == {"type": "ephemeral"}


class TestTTSRetry429:
    def test_retries_on_429_then_succeeds(self):
        from lifebook.config import TTSConfig
        from lifebook.tts import TTSClient

        cfg = TTSConfig(
            api_key="k", base_url="https://api.test",
            model="m", voice_id="v",
        )
        client = TTSClient(cfg)

        fail_resp = MagicMock()
        fail_resp.status_code = 429
        fail_resp.text = "rate limited"

        ok_resp = MagicMock()
        ok_resp.status_code = 200
        ok_resp.json.return_value = {
            "choices": [{"message": {"audio": {"data": __import__("base64").b64encode(b"\x00\x01").decode()}}}],
        }

        with patch("lifebook.tts.httpx.Client") as mock_cls, \
             patch("lifebook.tts.time.sleep") as mock_sleep:
            mock_post = MagicMock(side_effect=[fail_resp, ok_resp])
            mock_cls.return_value.__enter__ = MagicMock(
                return_value=MagicMock(post=mock_post),
            )
            mock_cls.return_value.__exit__ = MagicMock(return_value=False)
            result = client.synthesize("Hello")

        assert result == b"\x00\x01"
        assert mock_post.call_count == 2
        mock_sleep.assert_called_once_with(1)
