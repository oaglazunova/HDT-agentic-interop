from __future__ import annotations

import datetime as _dt
import json
import os
from pathlib import Path
from typing import Any, Dict

from hdt_config.settings import repo_root
from hdt_common.context import get_request_id
from hdt_common.errors import REDACT_TOKEN

_DEFAULT_TELEMETRY_DIR = (repo_root() / "artifacts" / "telemetry").resolve()
_TELEMETRY_DIR = Path(os.getenv("HDT_TELEMETRY_DIR", str(_DEFAULT_TELEMETRY_DIR))).expanduser().resolve()
_TELEMETRY_DIR.mkdir(parents=True, exist_ok=True)

_DISABLE_TELEMETRY = (os.getenv("HDT_DISABLE_TELEMETRY", "0").strip().lower() in {"1", "true", "yes"})


_SECRET_KEYS = {"authorization", "auth_bearer", "access_token", "token", "api_key", "apikey"}

_PII_KEYS = {
    "user_id",
    "email",
    "player_id",
    "account_user_id",
    "external_user_id",
}


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


def _redact_pii(obj: Any) -> Any:
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if isinstance(k, str) and k.strip().lower() in _PII_KEYS:
                out[k] = REDACT_TOKEN
            else:
                out[k] = _redact_pii(v)
        return out
    if isinstance(obj, list):
        return [_redact_pii(x) for x in obj]
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
        "ts": _dt.datetime.now(_dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "kind": kind,
        "name": name,
        "client_id": client_id,
        "request_id": rid,
        "corr_id": corr_id or rid,
        "args": payload,
        "ok": bool(ok),
        "ms": int(ms),
    }

    # Defense-in-depth:
    # 1) redact secrets (tokens, API keys)
    # 2) redact common PII keys (user identifiers, emails)
    # This keeps telemetry files safe to share as research artifacts.
    safe = _redact_pii(_redact_secrets(rec))
    p = _TELEMETRY_DIR / telemetry_file
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(safe, ensure_ascii=False) + "\n")


def telemetry_recent(n: int = 50, telemetry_file: str = "mcp-telemetry.jsonl") -> dict:
    """
    Return last N telemetry records (bounded) with secrets + PII redacted.
    """
    p = _TELEMETRY_DIR / telemetry_file
    if not p.exists():
        return {"records": []}

    # hard bounds (avoid huge reads)
    try:
        n_int = int(n)
    except Exception:
        n_int = 50
    n_int = max(1, min(n_int, 200))

    # Read a tail window larger than n to tolerate filtering/malformed lines later if needed
    tail_window = max(500, n_int * 5)
    lines = p.read_text(encoding="utf-8").splitlines()[-tail_window:]

    out = []
    for line in lines[-n_int:]:
        try:
            rec = json.loads(line)
        except Exception:
            continue
        # defense in depth: redact again on read
        rec = _redact_secrets(rec)
        rec = _redact_pii(rec)
        out.append(rec)

    return {"records": out}

