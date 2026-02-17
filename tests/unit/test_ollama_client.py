from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx
import pytest

from hdt_a2a.llm.ollama_client import OllamaClient, OllamaConfig


class DummyClient:
    """
    Mimics httpx.Client context manager and captures the outgoing JSON payload.
    Returns a fixed httpx.Response.
    """

    def __init__(
        self,
        response_json: dict[str, Any],
        *,
        status_code: int = 200,
        posted_payloads: list[dict[str, Any]] | None = None,
    ) -> None:
        self._response_json = response_json
        self._status_code = status_code
        self._posted_payloads = posted_payloads

    def __enter__(self) -> "DummyClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def post(self, url: str, **kwargs: Any) -> httpx.Response:
        payload = kwargs.get("json")
        if self._posted_payloads is not None and payload is not None:
            # deep copy to avoid accidental mutation
            self._posted_payloads.append(json.loads(json.dumps(payload)))
        return httpx.Response(self._status_code, json=self._response_json)


@dataclass
class DummyClientFactory:
    """
    Factory that returns a new DummyClient per instantiation, enabling retry tests.
    Each call to httpx.Client(...) consumes the next queued response.
    """

    responses: list[tuple[int, dict[str, Any]]]
    posted_payloads: list[dict[str, Any]]

    def __call__(self, timeout: float) -> DummyClient:
        assert self.responses, "No more queued DummyClient responses"
        status_code, body = self.responses.pop(0)
        return DummyClient(body, status_code=status_code, posted_payloads=self.posted_payloads)


def test_chat_json_parses_message_content_string(monkeypatch) -> None:
    fake = {"message": {"content": '{"plan_id":"x","plan_version":"1.0"}'}}
    monkeypatch.setattr(
        "hdt_a2a.llm.ollama_client.httpx.Client",
        lambda timeout: DummyClient(fake),
    )

    c = OllamaClient(OllamaConfig(model="dummy"))
    out = c.chat_json(
        [{"role": "user", "content": "hi"}],
        json_schema={"type": "object", "properties": {"plan_id": {"type": "string"}}, "required": ["plan_id"]},
    )
    assert out["plan_id"] == "x"


def test_chat_text_returns_string(monkeypatch) -> None:
    fake = {"message": {"content": "hello"}}
    monkeypatch.setattr(
        "hdt_a2a.llm.ollama_client.httpx.Client",
        lambda timeout: DummyClient(fake),
    )

    c = OllamaClient(OllamaConfig(model="dummy"))
    out = c.chat_text([{"role": "user", "content": "hi"}])
    assert out == "hello"


def test_normalizes_dict_message_content_to_json_string(monkeypatch) -> None:
    posted: list[dict[str, Any]] = []
    fake = {"message": {"content": "ok"}}

    monkeypatch.setattr(
        "hdt_a2a.llm.ollama_client.httpx.Client",
        lambda timeout: DummyClient(fake, posted_payloads=posted),
    )

    c = OllamaClient(OllamaConfig(model="dummy"))
    _ = c.chat_text([{"role": "user", "content": {"b": 2, "a": 1}}])

    assert len(posted) == 1
    sent = posted[0]
    # content must be valid JSON string, not "{'a': 1}" etc.
    assert sent["messages"][0]["content"] == '{"a":1,"b":2}'


def test_schema_is_minified_in_format(monkeypatch) -> None:
    posted: list[dict[str, Any]] = []
    fake = {"message": {"content": '{"plan_id":"x"}'}}

    monkeypatch.setattr(
        "hdt_a2a.llm.ollama_client.httpx.Client",
        lambda timeout: DummyClient(fake, posted_payloads=posted),
    )

    cfg = OllamaConfig(model="dummy", structured_mode="schema")
    c = OllamaClient(cfg)

    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "urn:test:schema",
        "title": "MappingPlan",
        "description": "Should be dropped in minified schema",
        "type": "object",
        "properties": {"plan_id": {"type": "string"}},
        "required": ["plan_id"],
    }

    out = c.chat_json([{"role": "user", "content": "hi"}], json_schema=schema)
    assert out["plan_id"] == "x"

    assert len(posted) == 1
    sent = posted[0]
    assert isinstance(sent["format"], dict)
    assert "$schema" not in sent["format"]
    assert "$id" not in sent["format"]
    assert "title" not in sent["format"]
    assert "description" not in sent["format"]
    assert sent["format"]["type"] == "object"


def test_auto_budget_falls_back_to_format_json(monkeypatch) -> None:
    posted: list[dict[str, Any]] = []
    fake = {"message": {"content": '{"plan_id":"x"}'}}

    monkeypatch.setattr(
        "hdt_a2a.llm.ollama_client.httpx.Client",
        lambda timeout: DummyClient(fake, posted_payloads=posted),
    )

    # Tiny budget forces auto mode to choose format="json"
    cfg = OllamaConfig(model="dummy", structured_mode="auto", structured_budget_bytes=1)
    c = OllamaClient(cfg)

    out = c.chat_json(
        [{"role": "user", "content": "hi"}],
        json_schema={"type": "object", "properties": {"plan_id": {"type": "string"}}, "required": ["plan_id"]},
    )
    assert out["plan_id"] == "x"

    assert len(posted) == 1
    assert posted[0]["format"] == "json"


def test_schema_mode_error_retries_once_with_format_json(monkeypatch) -> None:
    posted: list[dict[str, Any]] = []

    # First call (schema mode): Ollama error payload (simulates runner stop)
    # Second call (json mode fallback): valid JSON
    factory = DummyClientFactory(
        responses=[
            (200, {"error": "runner unexpectedly stopped"}),
            (200, {"message": {"content": '{"plan_id":"x"}'}}),
        ],
        posted_payloads=posted,
    )
    monkeypatch.setattr("hdt_a2a.llm.ollama_client.httpx.Client", factory)

    cfg = OllamaConfig(
        model="dummy",
        structured_mode="schema",
        fallback_to_json_on_error=True,
    )
    c = OllamaClient(cfg)

    out = c.chat_json(
        [{"role": "user", "content": "hi"}],
        json_schema={"type": "object", "properties": {"plan_id": {"type": "string"}}, "required": ["plan_id"]},
    )
    assert out["plan_id"] == "x"

    # Two attempts happened: first schema, then json fallback
    assert len(posted) == 2
    assert isinstance(posted[0]["format"], dict)  # schema attempt
    assert posted[1]["format"] == "json"          # fallback attempt
