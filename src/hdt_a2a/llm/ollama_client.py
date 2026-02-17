from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping, Sequence, Literal

import httpx


@dataclass(frozen=True)
class OllamaConfig:
    base_url: str = "http://localhost:11434"
    model: str = "qwen2.5:7b-instruct"
    timeout_s: float = 60.0

    # Generation defaults for structured JSON
    temperature: float = 0.0
    num_ctx: int = 2048
    num_predict: int = 700

    # Structured-output mode:
    # - json   : always request format="json" (most robust)
    # - schema : always request format=<json_schema>
    # - auto   : use schema only when payload is small enough; otherwise fall back to json
    structured_mode: Literal["json", "schema", "auto"] = "auto"

    # Guardrails to avoid Ollama runner crashes when prompts/schemas are large.
    # If (prompt_bytes + schema_bytes) exceeds this budget in auto mode, we use format="json".
    structured_budget_bytes: int = 25_000

    # If schema mode fails (HTTP error / runner stop / invalid JSON), retry once in json mode.
    fallback_to_json_on_error: bool = True


class OllamaError(RuntimeError):
    pass


def _normalize_messages(messages: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """
    Ollama expects messages like: [{"role":"system|user|assistant", "content":"..."}]
    Keep it minimal and deterministic.
    """
    def _norm_content(val: Any) -> str:
        if val is None:
            return ""
        if isinstance(val, str):
            return val
        if isinstance(val, (dict, list)):
            return json.dumps(val, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        return str(val)

    out: list[dict[str, Any]] = []
    for m in messages:
        role = str(m.get("role", "user"))
        out.append({"role": role, "content": _norm_content(m.get("content"))})
    return out


def _minify_schema(schema: Mapping[str, Any]) -> dict[str, Any]:
    drop_keys = {"$schema", "$id", "title", "description", "examples", "default"}
    return {k: v for k, v in schema.items() if k not in drop_keys}


def _estimate_bytes(obj: Any) -> int:
    try:
        return len(json.dumps(obj, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
    except Exception:
        return 0


def _contains_ref(obj: Any) -> bool:
    if isinstance(obj, dict):
        if "$ref" in obj:
            return True
        return any(_contains_ref(v) for v in obj.values())
    if isinstance(obj, list):
        return any(_contains_ref(v) for v in obj)
    return False

# === end helpers ==================================


class OllamaClient:
    def __init__(self, cfg: OllamaConfig) -> None:
        self.cfg = cfg

    def chat_text(self, messages: Sequence[Mapping[str, Any]]) -> str:
        payload = {"model": self.cfg.model, "messages": _normalize_messages(messages), "stream": False}
        with httpx.Client(timeout=self.cfg.timeout_s) as client:
            r = client.post(f"{self.cfg.base_url}/api/chat", json=payload)

        if r.status_code != 200:
            raise OllamaError(f"Ollama /api/chat failed: {r.status_code} {r.text}")

        data = r.json()
        if isinstance(data, dict) and data.get("error"):
            raise OllamaError(f"Ollama error: {data['error']}")

        msg = data.get("message") or {}
        content = msg.get("content")
        if not isinstance(content, str):
            raise OllamaError(f"Unexpected Ollama response shape (no message.content): {data}")
        return content

    def chat_json(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        json_schema: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized = _normalize_messages(messages)

        def _choose_format() -> tuple[Any, bool]:
            if json_schema is None:
                return "json", False

            mode = self.cfg.structured_mode
            if mode == "json":
                return "json", False

            schema_min = _minify_schema(json_schema)
            if mode == "schema":
                return schema_min, True

            # auto mode
            schema_bytes = _estimate_bytes(schema_min)
            prompt_bytes = _estimate_bytes(normalized)
            if (schema_bytes + prompt_bytes) > self.cfg.structured_budget_bytes:
                return "json", False
            if _contains_ref(schema_min):
                return "json", False
            return schema_min, True

        fmt, used_schema = _choose_format()

        payload_base: dict[str, Any] = {
            "model": self.cfg.model,
            "messages": normalized,
            "stream": False,
            "options": {
                "temperature": self.cfg.temperature,
                "num_ctx": self.cfg.num_ctx,
                "num_predict": self.cfg.num_predict,
            },
        }

        def _do_request(format_value: Any) -> dict[str, Any]:
            payload = dict(payload_base)
            payload["format"] = format_value

            with httpx.Client(timeout=self.cfg.timeout_s) as client:
                r = client.post(f"{self.cfg.base_url}/api/chat", json=payload)

            if r.status_code != 200:
                raise OllamaError(f"Ollama /api/chat failed: {r.status_code} {r.text}")

            data = r.json()
            if isinstance(data, dict) and data.get("error"):
                raise OllamaError(f"Ollama error: {data['error']}")

            msg = data.get("message") or {}
            content = msg.get("content")

            if isinstance(content, dict):
                return content

            if isinstance(content, str):
                s = content.strip()
                if not s:
                    raise OllamaError(f"Ollama returned empty content for structured output: {data}")
                try:
                    parsed = json.loads(s)
                except Exception as ex:
                    raise OllamaError(f"Failed to parse JSON from message.content: {ex}; startswith={s[:300]!r}")
                if not isinstance(parsed, dict):
                    raise OllamaError(f"Structured output is not a JSON object: {type(parsed)} {parsed!r}")
                return parsed

            raise OllamaError(f"Unexpected structured output type: {type(content)}; response={data}")

        try:
            return _do_request(fmt)
        except Exception:
            if used_schema and self.cfg.fallback_to_json_on_error:
                return _do_request("json")
            raise