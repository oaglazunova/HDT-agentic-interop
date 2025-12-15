from __future__ import annotations

import datetime as _dt
import json
import os
from pathlib import Path
from typing import Any, Dict

from HDT_MCP.core.context import get_request_id
from HDT_MCP.core.errors import REDACT_TOKEN

_TELEMETRY_DIR = Path(os.getenv("HDT_TELEMETRY_DIR", str(Path(__file__).resolve().parents[1] / "telemetry")))
_TELEMETRY_DIR.mkdir(parents=True, exist_ok=True)

_DISABLE_TELEMETRY = (os.getenv("HDT_DISABLE_TELEMETRY", "0").strip().lower() in {"1", "true", "yes"})


_SECRET_KEYS = {"authorization", "auth_bearer", "access_token", "token", "api_key", "apikey"}


def _redact_secrets(obj: Any) -> Any:
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if isinstance(k, str) and k.strip().lower() in _SECRET_KEYS:
                if isinstance(v, str) and v.strip().lower().startswith("bearer "):
                    out[k] = "Bearer " + REDACT_TOKEN
                else:
                    out[k] = REDACT_TOKEN
            else:
                out[k] = _redact_secrets(v)
        return out
    if isinstance(obj, list):
        return [_redact_secrets(x) for x in obj]
    return obj


def log_event(
    kind: str,
    name: str,
    args: dict | None = None,
    ok: bool = True,
    ms: int = 0,
    *,
    client_id: str | None = None,
    corr_id: str | None = None,
    telemetry_file: str = "mcp-telemetry.jsonl",
) -> None:
    """
    Append JSONL telemetry for tools/resources.
    """
    if _DISABLE_TELEMETRY:
        return

    rid = get_request_id()
    payload = {} if args is None else dict(args)

    rec = {
        "ts": _dt.datetime.utcnow().isoformat() + "Z",
        "kind": kind,
        "name": name,
        "client_id": client_id,
        "request_id": rid,
        "corr_id": corr_id or rid,
        "args": payload,
        "ok": bool(ok),
        "ms": int(ms),
    }

    safe = _redact_secrets(rec)
    p = _TELEMETRY_DIR / telemetry_file
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(safe, ensure_ascii=False) + "\n")


def telemetry_recent(n: int = 50, telemetry_file: str = "mcp-telemetry.jsonl") -> dict:
    p = _TELEMETRY_DIR / telemetry_file
    if not p.exists():
        return {"records": []}
    lines = p.read_text(encoding="utf-8").splitlines()[-int(n):]
    return {"records": [json.loads(x) for x in lines]}
