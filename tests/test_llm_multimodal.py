"""Tests for multimodal (image) support in LLMClient.structured_call."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from lifebook.config import ImageConfig, LLMConfig
from lifebook.image_processor import ImageData
from lifebook.llm import LLMClient


def _make_llm():
    cfg = LLMConfig(api_key="fake", base_url="https://fake.api")
    with patch("lifebook.llm.anthropic.Anthropic"):
        client = LLMClient(cfg)
    return client


def _tool_block(name: str, input_data: dict):
    return SimpleNamespace(type="tool_use", id="t1", name=name, input=input_data)


def _response(blocks, stop_reason="tool_use"):
    return SimpleNamespace(content=blocks, stop_reason=stop_reason)


def _fake_image_data() -> ImageData:
    return ImageData(
        base64_data="aGVsbG8=",
        media_type="image/jpeg",
        original_size=1000,
        compressed_size=500,
        width=100,
        height=100,
    )


class TestStructuredCallMultimodal:
    def test_with_image_sends_multimodal_content(self):
        llm = _make_llm()
        llm.client.messages.create.return_value = _response(
            [_tool_block("extract_note", {"title": "Test", "confidence": 0.9})]
        )
        img = _fake_image_data()
        llm.structured_call(
            tool_name="extract_note",
            tool_description="desc",
            input_schema={},
            user_prompt="Describe this image",
            images=[img],
        )
        call_kwargs = llm.client.messages.create.call_args.kwargs
        messages = call_kwargs["messages"]
        assert len(messages) == 1
        content = messages[0]["content"]
        assert isinstance(content, list)
        assert content[0]["type"] == "image"
        assert content[0]["source"]["type"] == "base64"
        assert content[0]["source"]["media_type"] == "image/jpeg"
        assert content[0]["source"]["data"] == "aGVsbG8="
        assert content[1]["type"] == "text"
        assert content[1]["text"] == "Describe this image"

    def test_without_image_sends_text_string(self):
        llm = _make_llm()
        llm.client.messages.create.return_value = _response(
            [_tool_block("extract_note", {"title": "T", "confidence": 0.8})]
        )
        llm.structured_call(
            tool_name="extract_note",
            tool_description="desc",
            input_schema={},
            user_prompt="plain text prompt",
        )
        call_kwargs = llm.client.messages.create.call_args.kwargs
        messages = call_kwargs["messages"]
        assert messages[0]["content"] == "plain text prompt"

    def test_multiple_images_all_included(self):
        llm = _make_llm()
        llm.client.messages.create.return_value = _response(
            [_tool_block("extract_note", {"title": "T", "confidence": 0.9})]
        )
        imgs = [_fake_image_data(), _fake_image_data()]
        llm.structured_call(
            tool_name="extract_note",
            tool_description="desc",
            input_schema={},
            user_prompt="two images",
            images=imgs,
        )
        content = llm.client.messages.create.call_args.kwargs["messages"][0]["content"]
        image_blocks = [b for b in content if b["type"] == "image"]
        assert len(image_blocks) == 2

    def test_vision_model_passed_through(self):
        llm = _make_llm()
        llm.client.messages.create.return_value = _response(
            [_tool_block("extract_note", {"title": "T", "confidence": 0.9})]
        )
        llm.structured_call(
            tool_name="extract_note",
            tool_description="desc",
            input_schema={},
            user_prompt="prompt",
            model="MiMo-VL-7B-RL",
            images=[_fake_image_data()],
        )
        call_kwargs = llm.client.messages.create.call_args.kwargs
        assert call_kwargs["model"] == "MiMo-VL-7B-RL"
