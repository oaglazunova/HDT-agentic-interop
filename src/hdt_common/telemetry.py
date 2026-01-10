from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from hdt_config.settings import repo_root
from hdt_common.context import get_request_id
from hdt_common.errors import REDACT_TOKEN

_DEFAULT_TELEMETRY_DIR = (repo_root() / "artifacts" / "telemetry").resolve()
_TELEMETRY_DIR = Path(os.getenv("HDT_TELEMETRY_DIR", str(_DEFAULT_TELEMETRY_DIR))).expanduser().resolve()
_TELEMETRY_DIR.mkdir(parents=True, exist_ok=True)

_DISABLE_TELEMETRY = (os.getenv("HDT_DISABLE_TELEMETRY", "0").strip().lower() in {"1", "true", "yes"})

# Optional: privacy-preserving per-subject linkability.
# If set, we will compute `subject_hash` from the first `user_id` found in the event args.
# This allows per-citizen governance without writing the raw user id into telemetry.
_TELEMETRY_SUBJECT_SALT = os.getenv("HDT_TELEMETRY_SUBJECT_SALT", "").strip()

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


def _find_first_key(obj: Any, *, key: str) -> Any | None:
    """Best-effort recursive search for a key in nested dict/list structures."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(k, str) and k.strip().lower() == key:
                return v
        for v in obj.values():
            found = _find_first_key(v, key=key)
            if found is not None:
                return found
        return None
    if isinstance(obj, list):
        for item in obj:
            found = _find_first_key(item, key=key)
            if found is not None:
                return found
    return None


def _hash_subject(user_id: Any) -> str | None:
    if not _TELEMETRY_SUBJECT_SALT:
        return None
    if user_id is None:
        return None
    if user_id == REDACT_TOKEN:
        return None
    try:
        s = f"{_TELEMETRY_SUBJECT_SALT}:{user_id}".encode("utf-8")
        return hashlib.sha256(s).hexdigest()[:16]
    except Exception:
        return None


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
    """Append JSONL telemetry for tools/resources."""
    if _DISABLE_TELEMETRY:
        return

    rid = get_request_id()
    payload = {} if args is None else dict(args)

    rec: dict[str, Any] = {
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

    # Optional: derive a privacy-preserving per-subject key.
    # We compute this BEFORE redaction, then store only the hash.
    uid = _find_first_key(payload, key="user_id")
    subject_hash = _hash_subject(uid)
    if subject_hash:
        rec["subject_hash"] = subject_hash

    # Defense-in-depth:
    # 1) redact secrets (tokens, API keys)
    # 2) redact common PII keys (user identifiers, emails)
    # This keeps telemetry files safe to share as research artifacts.
    safe = _redact_pii(_redact_secrets(rec))
    p = _TELEMETRY_DIR / telemetry_file
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(safe, ensure_ascii=False) + "\n")


def telemetry_recent(n: int = 50, telemetry_file: str = "mcp-telemetry.jsonl") -> dict:
    """Return last N telemetry records (bounded) with secrets + PII redacted."""
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

    out: list[dict[str, Any]] = []
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


def _parse_ts(ts: str | None) -> _dt.datetime | None:
    if not ts:
        return None
    try:
        # expected format: 2025-01-01T00:00:00Z
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        return _dt.datetime.fromisoformat(ts)
    except Exception:
        return None


def telemetry_query(
    n: int = 50,
    *,
    lookback_s: int | None = None,
    since_ts: str | None = None,
    client_id: str | None = None,
    tool: str | None = None,
    tool_prefix: str | None = None,
    purpose: str | None = None,
    ok: bool | None = None,
    error_code: str | None = None,
    subject_hash: str | None = None,
    telemetry_file: str = "mcp-telemetry.jsonl",
) -> dict:
    """
    Filtered telemetry query over the local JSONL store.

    This is intentionally bounded (tail-read + filters) to keep the tool safe and fast.

    Notes:
    - Telemetry records are already redacted on write; we redact again on read.
    - Filters are best-effort; malformed lines are skipped.
    """
    p = _TELEMETRY_DIR / telemetry_file
    if not p.exists():
        return {"records": []}

    # hard bounds
    try:
        n_int = int(n)
    except Exception:
        n_int = 50
    n_int = max(1, min(n_int, 200))

    # Time window
    now = _dt.datetime.now(_dt.timezone.utc)
    since: _dt.datetime | None = None
    if lookback_s is not None:
        try:
            lb = max(0, int(lookback_s))
        except Exception:
            lb = 0
        since = now - _dt.timedelta(seconds=lb)
    if since_ts:
        parsed = _parse_ts(since_ts)
        if parsed is not None:
            # If both provided, take the more restrictive (later) bound.
            since = parsed if since is None else max(since, parsed)

    # Read a tail window larger than n to tolerate filtering.
    # Keep it bounded to avoid huge reads in CI.
    tail_window = 5000
    lines = p.read_text(encoding="utf-8").splitlines()[-tail_window:]

    # Iterate newest-first; collect until we have n matches
    matches: list[dict[str, Any]] = []
    for line in reversed(lines):
        try:
            rec = json.loads(line)
        except Exception:
            continue

        # Time filter (best-effort)
        if since is not None:
            ts = _parse_ts(rec.get("ts"))
            if ts is not None and ts < since:
                # Since we're going backwards in time, we can break early.
                break

        if client_id is not None and rec.get("client_id") != client_id:
            continue

        if subject_hash is not None and rec.get("subject_hash") != subject_hash:
            continue

        name = rec.get("name")
        if tool is not None and name != tool:
            continue
        if tool_prefix is not None and (not isinstance(name, str) or not name.startswith(tool_prefix)):
            continue

        # instrumented tools store purpose in rec['args']['purpose']
        if purpose is not None:
            rec_purpose = None
            try:
                rec_purpose = (rec.get("args") or {}).get("purpose")
            except Exception:
                rec_purpose = None
            if (rec_purpose or "") != purpose:
                continue

        if ok is not None and bool(rec.get("ok")) != bool(ok):
            continue

        if error_code is not None:
            code = None
            try:
                err = (rec.get("args") or {}).get("error")
                if isinstance(err, dict):
                    code = err.get("code")
            except Exception:
                code = None
            if code != error_code:
                continue

        # defense-in-depth: redact again on read
        rec = _redact_secrets(rec)
        rec = _redact_pii(rec)
        matches.append(rec)

        if len(matches) >= n_int:
            break

    matches.reverse()
    return {"records": matches}
