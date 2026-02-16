from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import httpx


@dataclass(frozen=True)
class OllamaConfig:
    base_url: str = "http://localhost:11434"
    model: str = "qwen2.5:7b-instruct"
    timeout_s: float = 60.0


class OllamaError(RuntimeError):
    pass


def _normalize_messages(messages: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """
    Ollama expects messages like: [{"role":"system|user|assistant", "content":"..."}]
    Keep it minimal and deterministic.
    """
    out: list[dict[str, Any]] = []
    for m in messages:
        role = str(m.get("role", "user"))
        content = m.get("content")
        if content is None:
            content = ""
        out.append({"role": role, "content": str(content)})
    return out


class OllamaClient:
    def __init__(self, cfg: OllamaConfig) -> None:
        self.cfg = cfg

    def chat_text(self, messages: Sequence[Mapping[str, Any]]) -> str:
        payload = {
            "model": self.cfg.model,
            "messages": _normalize_messages(messages),
            "stream": False,
        }
        with httpx.Client(timeout=self.cfg.timeout_s) as client:
            r = client.post(f"{self.cfg.base_url}/api/chat", json=payload)
            if r.status_code != 200:
                raise OllamaError(f"Ollama /api/chat failed: {r.status_code} {r.text}")
            data = r.json()
        msg = data.get("message") or {}
        content = msg.get("content")
        if not isinstance(content, str):
            raise OllamaError(f"Unexpected Ollama response shape (no message.content): {data}")
        return content

    def chat_json(self, messages: Sequence[Mapping[str, Any]], *, json_schema: Mapping[str, Any]) -> dict[str, Any]:
        """
        Structured output: passes json_schema as the 'format' argument to Ollama /api/chat.
        Ollama returns message.content as a JSON string (typically) OR an object in some builds.
        We accept both, but normalize to dict.
        """
        payload = {
            "model": self.cfg.model,
            "messages": _normalize_messages(messages),
            "stream": False,
            "format": json_schema,
        }
        with httpx.Client(timeout=self.cfg.timeout_s) as client:
            r = client.post(f"{self.cfg.base_url}/api/chat", json=payload)
            if r.status_code != 200:
                raise OllamaError(f"Ollama /api/chat failed: {r.status_code} {r.text}")
            data = r.json()

        msg = data.get("message") or {}
        content = msg.get("content")

        # Most common: content is a JSON string
        if isinstance(content, str):
            content_str = content.strip()
            if not content_str:
                raise OllamaError(f"Ollama returned empty content for structured output: {data}")
            try:
                parsed = httpx.Response(200, content=content_str).json()
            except Exception as ex:
                raise OllamaError(f"Failed to parse structured JSON from Ollama message.content: {ex}; content={content_str!r}")
            if not isinstance(parsed, dict):
                raise OllamaError(f"Structured output is not a JSON object: {parsed!r}")
            return parsed

        # Some variants: content already deserialized
        if isinstance(content, dict):
            return content

        raise OllamaError(f"Unexpected structured output type: {type(content)}; response={data}")
