"""Feishu WebSocket transport: connection lifecycle and message sending."""
from __future__ import annotations

import json
import logging
from typing import Any, Callable

import httpx
import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    CreateMessageRequest,
    CreateMessageRequestBody,
    GetMessageResourceRequest,
    GetMessageResourceRequestBuilder,
    P2ImMessageReceiveV1,
    ReplyMessageRequest,
    ReplyMessageRequestBody,
)

from .config import FeishuConfig

logger = logging.getLogger(__name__)


class FeishuTransport:
    """Encapsulates Feishu WebSocket connection and HTTP messaging."""

    def __init__(self, cfg: FeishuConfig):
        self.cfg = cfg
        self.api = (
            lark.Client.builder()
            .app_id(cfg.app_id)
            .app_secret(cfg.app_secret)
            .log_level(lark.LogLevel.WARNING)
            .build()
        )
        self._ws_client: lark.ws.Client | None = None

    def send_text(self, chat_id: str, text: str) -> str | None:
        """Send a text message to a chat. Returns message_id on success."""
        body = (
            CreateMessageRequestBody.builder()
            .receive_id(chat_id)
            .msg_type("text")
            .content(json.dumps({"text": text}, ensure_ascii=False))
            .build()
        )
        req = (
            CreateMessageRequest.builder()
            .receive_id_type("chat_id")
            .request_body(body)
            .build()
        )
        resp = self.api.im.v1.message.create(req)
        if not resp.success():
            logger.error("send_text failed: %s %s", resp.code, resp.msg)
            return None
        return resp.data.message_id

    def reply_text(self, message_id: str, text: str) -> str | None:
        """Reply (threaded) to a specific message."""
        body = (
            ReplyMessageRequestBody.builder()
            .msg_type("text")
            .content(json.dumps({"text": text}, ensure_ascii=False))
            .build()
        )
        req = (
            ReplyMessageRequest.builder()
            .message_id(message_id)
            .request_body(body)
            .build()
        )
        resp = self.api.im.v1.message.reply(req)
        if not resp.success():
            logger.error("reply_text failed: %s %s", resp.code, resp.msg)
            return None
        return resp.data.message_id

    def download_image_message(self, message_id: str, image_key: str) -> bytes | None:
        """Download an image resource attached to a message.

        Returns raw image bytes on success, or None on failure.
        """
        req = (
            GetMessageResourceRequestBuilder()
            .message_id(message_id)
            .file_key(image_key)
            .type("image")
            .build()
        )
        resp = self.api.im.v1.message_resource.get(req)
        if not resp.success():
            logger.error(
                "download_image_message failed: %s %s (message=%s key=%s)",
                resp.code, resp.msg, message_id, image_key,
            )
            return None
        file_obj = resp.file
        if file_obj is None:
            logger.error("download_image_message: no file in response")
            return None
        return file_obj.read()

    def _tenant_token(self) -> str | None:
        """Get tenant_access_token via direct HTTP."""
        resp = httpx.post(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": self.cfg.app_id, "app_secret": self.cfg.app_secret},
        )
        data = resp.json()
        if data.get("code") != 0:
            logger.error("tenant_token failed: %s", data)
            return None
        return data["tenant_access_token"]

    def upload_file(
        self, file_bytes: bytes, file_name: str,
        file_type: str = "file", duration: int | None = None,
    ) -> str | None:
        """Upload a file to Feishu via multipart/form-data. Returns file_key on success."""
        token = self._tenant_token()
        if not token:
            return None
        form_data: dict[str, Any] = {"file_type": file_type, "file_name": file_name}
        if duration is not None:
            form_data["duration"] = str(int(duration * 1000))
        resp = httpx.post(
            "https://open.feishu.cn/open-apis/im/v1/files",
            headers={"Authorization": f"Bearer {token}"},
            data=form_data,
            files={"file": (file_name, file_bytes)},
            timeout=60,
        )
        result = resp.json()
        if result.get("code", -1) != 0:
            logger.error("upload_file failed: %s", result.get("msg"))
            return None
        return result["data"]["file_key"]

    def send_audio(self, chat_id: str, file_key: str) -> str | None:
        """Send an audio (voice) message to a chat. Returns message_id on success."""
        body = (
            CreateMessageRequestBody.builder()
            .receive_id(chat_id)
            .msg_type("audio")
            .content(json.dumps({"file_key": file_key}, ensure_ascii=False))
            .build()
        )
        req = (
            CreateMessageRequest.builder()
            .receive_id_type("chat_id")
            .request_body(body)
            .build()
        )
        resp = self.api.im.v1.message.create(req)
        if not resp.success():
            logger.error("send_audio failed: %s %s", resp.code, resp.msg)
            return None
        return resp.data.message_id

    def send_file(self, chat_id: str, file_key: str) -> str | None:
        """Send a file message to a chat. Returns message_id on success."""
        body = (
            CreateMessageRequestBody.builder()
            .receive_id(chat_id)
            .msg_type("file")
            .content(json.dumps({"file_key": file_key}, ensure_ascii=False))
            .build()
        )
        req = (
            CreateMessageRequest.builder()
            .receive_id_type("chat_id")
            .request_body(body)
            .build()
        )
        resp = self.api.im.v1.message.create(req)
        if not resp.success():
            logger.error("send_file failed: %s %s", resp.code, resp.msg)
            return None
        return resp.data.message_id

    def start(self, message_handler: Callable[[P2ImMessageReceiveV1], None]) -> None:
        """Start WebSocket long-connection. Blocks until stopped."""
        handler = (
            lark.EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(message_handler)
            .build()
        )
        self._ws_client = lark.ws.Client(
            app_id=self.cfg.app_id,
            app_secret=self.cfg.app_secret,
            event_handler=handler,
            log_level=lark.LogLevel.WARNING,
        )
        logger.info("Feishu bot starting (long-connection WebSocket)...")
        self._ws_client.start()

    def stop(self) -> None:
        """Stop WebSocket connection."""
        if self._ws_client is not None:
            self._ws_client.close()
            logger.info("Feishu WebSocket closed")
