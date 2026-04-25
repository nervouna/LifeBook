"""Writer service: state management and chat orchestration."""
from __future__ import annotations

from lifebook.config import Config
from lifebook.llm import LLMClient
from lifebook.writer import Writer


class WriterService:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._writer: Writer | None = None

    def _get_writer(self) -> Writer:
        if self._writer is None:
            self._writer = Writer(self.cfg, LLMClient(self.cfg.llm))
        return self._writer

    def get_status(self) -> dict:
        w = self._get_writer()
        if not w.active:
            return {"active": False, "stage": None, "title": None}
        meta, _ = w._load_draft()
        return {
            "active": True,
            "stage": w.stage,
            "title": meta.get("title") if meta else None,
        }

    def start(self, idea: str) -> dict:
        w = self._get_writer()
        reply = w.start(idea)
        return {"reply": reply, "stage": w.stage}

    def chat(self, message: str) -> dict:
        w = self._get_writer()
        if not w.active:
            return {"reply": "当前没有进行中的写作。请先开始一个新的写作会话。", "stage": None}
        reply = w.handle_message(message)
        return {"reply": reply, "stage": w.stage}

    def publish(self, force: bool = False) -> dict:
        w = self._get_writer()
        reply = w.publish(force=force)
        self._writer = None
        return {"reply": reply}

    def restore(self) -> dict:
        w = self._get_writer()
        reply = w.restore_draft()
        return {"reply": reply}
