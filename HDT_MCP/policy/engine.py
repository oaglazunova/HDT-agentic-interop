from __future__ import annotations

import copy
import json
import threading
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Dict, List, Optional

from HDT_MCP.core.errors import REDACT_TOKEN, typed_error

# Policy location (defaults to config/policy.json)
CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"
_POLICY_PATH: Path = Path((__import__("os").environ.get("HDT_POLICY_PATH", str(CONFIG_DIR / "policy.json"))))

_POLICY_CACHE: dict | None = None
_POLICY_SIG: tuple[int, int] | None = None  # (st_mtime_ns, st_size)
_POLICIES_LOCK = threading.Lock()

# Tests can monkeypatch this
_POLICY_OVERRIDE: dict | None = None

# last policy meta for the current call (thread/async-safe)
_POLICY_LAST = ContextVar(
    "policy_last",
    default={"redactions": 0, "allowed": True, "purpose": "", "tool": ""},
)


def policy_reset_cache() -> None:
    global _POLICY_CACHE, _POLICY_SIG
    with _POLICIES_LOCK:
        _POLICY_CACHE = None
        _POLICY_SIG = None


def policy_last_meta() -> dict:
    return _POLICY_LAST.get()


def _load_policy_file() -> dict:
    try:
        with _POLICY_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception:
        # fail-closed would be another choice; for now return empty policy
        return {}


def _policy() -> dict:
    global _POLICY_CACHE, _POLICY_SIG
    if _POLICY_OVERRIDE is not None:
        return _POLICY_OVERRIDE

    try:
        st = _POLICY_PATH.stat()
    except FileNotFoundError:
        with _POLICIES_LOCK:
            _POLICY_CACHE, _POLICY_SIG = {}, None
        return {}

    sig = (st.st_mtime_ns, st.st_size)
    with _POLICIES_LOCK:
        if _POLICY_CACHE is None or _POLICY_SIG != sig:
            _POLICY_CACHE = _load_policy_file()
            _POLICY_SIG = sig
        return _POLICY_CACHE or {}


def _merge_rule(base: dict, override: dict | None) -> dict:
    out = dict(base or {})
    if override:
        out.update(override)
    out.setdefault("allow", True)
    out.setdefault("redact", [])
    return out


def _resolve_rule(purpose: str, tool_name: str, client_id: str | None) -> dict:
    pol = _policy()
    rule = _merge_rule({}, (pol.get("defaults", {}) or {}).get(purpose))
    if client_id:
        rule = _merge_rule(rule, ((pol.get("clients", {}) or {}).get(client_id, {}) or {}).get(purpose))
    rule = _merge_rule(rule, (((pol.get("tools", {}) or {}).get(tool_name, {}) or {}).get(purpose)))
    return rule


def _redact_path(node: object, parts: list[str]) -> int:
    if not parts:
        return 0
    key, rest = parts[0], parts[1:]

    if isinstance(node, list):
        return sum(_redact_path(item, parts) for item in node)

    if not isinstance(node, dict) or key not in node:
        return 0

    if not rest:
        node[key] = REDACT_TOKEN
        return 1

    return _redact_path(node[key], rest)


def _redact_inplace(doc: object, paths: list[str]) -> int:
    total = 0
    for p in paths or []:
        if not isinstance(p, str) or not p:
            continue
        total += _redact_path(doc, p.split("."))
    return total


def apply_policy(purpose: str, tool_name: str, payload: dict, *, client_id: str | None = None) -> dict:
    """
    Mutates payload in place when allowed (redaction) and returns payload.
    If denied, returns a typed error and does NOT mutate payload.
    """
    rule = _resolve_rule(purpose, tool_name, client_id)

    if not rule.get("allow", True):
        _POLICY_LAST.set({"redactions": 0, "allowed": False, "purpose": purpose, "tool": tool_name})
        return typed_error("denied_by_policy", "Access denied by policy", purpose=purpose, tool=tool_name)

    redact_paths = rule.get("redact") or []
    redactions = _redact_inplace(payload, redact_paths) if redact_paths else 0
    _POLICY_LAST.set({"redactions": redactions, "allowed": True, "purpose": purpose, "tool": tool_name})
    return payload


def apply_policy_safe(purpose: str, tool_name: str, payload: dict, *, client_id: str | None = None) -> dict:
    """Apply policy to a deep copy to avoid mutating cached/shared objects."""
    clone = copy.deepcopy(payload)
    return apply_policy(purpose, tool_name, clone, client_id=client_id)


def apply_policy_metrics(purpose: str, tool_name: str, payload: dict, *, client_id: str | None = None):
    """
    Convenience wrapper for tests/metrics: returns (result_payload, redactions_count).
    """
    result = apply_policy_safe(purpose, tool_name, payload, client_id=client_id)
    meta = policy_last_meta() or {}
    return result, int(meta.get("redactions", 0))
