from __future__ import annotations

from typing import Any
import httpx
import pytest

from hdt_a2a.llm.ollama_client import OllamaClient, OllamaConfig


class DummyClient:
    def __init__(self, response_json: dict[str, Any], status_code: int = 200) -> None:
        self._response_json = response_json
        self._status_code = status_code

    def __enter__(self) -> "DummyClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def post(self, url: str, json: dict[str, Any]) -> httpx.Response:
        # simulate httpx.Response
        return httpx.Response(self._status_code, json=self._response_json)


def test_chat_json_parses_message_content_string(monkeypatch) -> None:
    fake = {"message": {"content": '{"plan_id":"x","plan_version":"1.0"}'}}
    monkeypatch.setattr("hdt_a2a.llm.ollama_client.httpx.Client", lambda timeout: DummyClient(fake))

    c = OllamaClient(OllamaConfig(model="dummy"))
    out = c.chat_json(
        [{"role": "user", "content": "hi"}],
        json_schema={"type": "object", "properties": {"plan_id": {"type": "string"}}, "required": ["plan_id"]},
    )
    assert out["plan_id"] == "x"


def test_chat_text_returns_string(monkeypatch) -> None:
    fake = {"message": {"content": "hello"}}
    monkeypatch.setattr("hdt_a2a.llm.ollama_client.httpx.Client", lambda timeout: DummyClient(fake))

    c = OllamaClient(OllamaConfig(model="dummy"))
    out = c.chat_text([{"role": "user", "content": "hi"}])
    assert out == "hello"
