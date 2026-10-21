"""Model client. Agents talk to the LLM protocol, so tests can script the model."""
from __future__ import annotations

from typing import Protocol

import httpx

from .config import Config
from .gate import BACKGROUND, ModelGate


class LLM(Protocol):
    def chat(self, messages: list[dict], tools: list[dict] | None = None, priority: int = BACKGROUND,
             json_schema: dict | None = None) -> dict:
        """Return the assistant message: {"content": str, "tool_calls": [...]}"""


class OllamaLLM:
    def __init__(self, cfg: Config, gate: ModelGate) -> None:
        self.cfg, self.gate = cfg, gate

    def chat(self, messages, tools=None, priority=BACKGROUND, json_schema=None):
        body = {"model": self.cfg.model, "messages": messages, "stream": False, "think": False, "keep_alive": "30m",
                "options": {"num_ctx": self.cfg.num_ctx, "temperature": 0.1}}
        if tools:
            body["tools"] = tools
        if json_schema:
            body["format"] = json_schema
        with self.gate.slot(priority, timeout=900):
            r = httpx.post(f"{self.cfg.ollama_url}/api/chat", json=body, timeout=600)
        r.raise_for_status()
        m = r.json()["message"]
        return {"role": "assistant", "content": m.get("content") or "", "tool_calls": m.get("tool_calls") or []}
