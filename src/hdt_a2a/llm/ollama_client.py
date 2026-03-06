from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping, Sequence, Literal
import httpx
import re
import logging


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


# === helpers =====================================

_JSON_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE | re.MULTILINE)
_TRAILING_COMMAS_RE = re.compile(r",(\s*[}\]])")


def _extract_json_object(text: str) -> str:
    """Best-effort: take substring from first '{' to last '}'."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return text.strip()
    return text[start : end + 1].strip()


def _loads_relaxed_json(content: Any) -> dict[str, Any]:
    # Already parsed by Ollama / httpx?
    if isinstance(content, dict):
        return content

    if isinstance(content, bytes):
        text = content.decode("utf-8-sig", errors="replace")
    else:
        text = str(content)

    # strip BOM + fences
    text = text.lstrip("\ufeff")
    text = _JSON_FENCE_RE.sub("", text).strip()

    # if model included extra chatter, try to isolate the object
    candidate = _extract_json_object(text)

    # 1) strict parse
    try:
        obj = json.loads(candidate)
        if isinstance(obj, dict):
            return obj
        raise ValueError(f"expected JSON object, got {type(obj).__name__}")
    except json.JSONDecodeError:
        pass

    # 2) remove trailing commas and retry
    candidate2 = _TRAILING_COMMAS_RE.sub(r"\1", candidate)
    obj = json.loads(candidate2)
    if not isinstance(obj, dict):
        raise ValueError(f"expected JSON object, got {type(obj).__name__}")
    return obj


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
        self._log = logging.getLogger(__name__)

    def chat_text(self, messages: Sequence[Mapping[str, Any]]) -> str:
        payload = {"model": self.cfg.model, "messages": _normalize_messages(messages), "stream": False}
        timeout = httpx.Timeout(connect=5.0, read=self.cfg.timeout_s, write=30.0, pool=5.0)
        with httpx.Client(timeout=timeout) as client:
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
        self._log.info(
            "ollama chat_json: model=%s structured_mode=%s used_schema=%s timeout_s=%.1f num_ctx=%s num_predict=%s",
            self.cfg.model,
            self.cfg.structured_mode,
            used_schema,
            self.cfg.timeout_s,
            self.cfg.num_ctx,
            self.cfg.num_predict,
        )

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

            timeout = httpx.Timeout(connect=5.0, read=self.cfg.timeout_s, write=30.0, pool=5.0)
            with httpx.Client(timeout=timeout) as client:
                r = client.post(f"{self.cfg.base_url}/api/chat", json=payload)

            if r.status_code != 200:
                raise OllamaError(f"Ollama /api/chat failed: {r.status_code} {r.text}")

            data = r.json()
            if isinstance(data, dict) and data.get("error"):
                raise OllamaError(f"Ollama error: {data['error']}")

            msg = data.get("message") or {}
            content = msg.get("content")

            msg = data.get("message") or {}
            content = msg.get("content")

            # Accept either dict (already parsed) or string/bytes that need parsing.
            if isinstance(content, (dict, str, bytes)):
                try:
                    return _loads_relaxed_json(content)
                except Exception as ex:
                    # Make debugging actionable: show head+tail (content can be long)
                    raw = content.decode("utf-8", errors="replace") if isinstance(content, bytes) else str(content)
                    head = raw[:300]
                    tail = raw[-200:] if len(raw) > 200 else raw
                    raise OllamaError(f"Failed to parse JSON from message.content: {ex}; head={head!r}; tail={tail!r}")

            raise OllamaError(f"Unexpected structured output type: {type(content)}; response={data}")

        try:
            return _do_request(fmt)
        except Exception:
            if used_schema and self.cfg.fallback_to_json_on_error:
                return _do_request("json")
            raise
