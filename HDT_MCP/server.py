"""
HDT_MCP.server

Compatibility façade for legacy unit tests.

Production entrypoint for Option D is:
  - HDT_MCP.server_option_d (external HDT MCP)
  - HDT_SOURCES_MCP.server (internal Sources MCP)

This module intentionally keeps a small set of synchronous helpers that tests
import directly (policy/telemetry wrappers + a few tool-like functions).
"""

from __future__ import annotations

import copy
import json
import os
import threading
import time as _time
from pathlib import Path
from typing import Any, Dict, Optional

# --- extracted modules (your new structure) ---
import HDT_MCP.policy.engine as pol
from HDT_MCP.observability import telemetry as tel
from HDT_MCP.core.errors import typed_error, REDACT_TOKEN

# -----------------------------
# Backwards-compatible globals
# -----------------------------

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"

# tests patch these on HDT_MCP.server (so keep them here)
_POLICY_PATH: Path = Path(os.getenv("HDT_POLICY_PATH", str(CONFIG_DIR / "policy.json")))
_POLICY_OVERRIDE: dict | None = None

# Some old tests/fixtures patch this flag; keep it for compatibility (not required by engine)
_ENABLE_POLICY: bool = (os.getenv("HDT_ENABLE_POLICY_TOOLS", "0") or "").strip().lower() in {"1", "true", "yes", "on"}

# Telemetry dir is referenced by tests
_TELEMETRY_DIR = Path(os.getenv("HDT_TELEMETRY_DIR", str(Path(__file__).parent / "telemetry")))
_TELEMETRY_DIR.mkdir(parents=True, exist_ok=True)

# Simple response cache is referenced by tests
_cache: dict[tuple[str, tuple], tuple[float, dict]] = {}
_CACHE_TTL = int(os.getenv("HDT_CACHE_TTL", "15"))
_cache_lock = threading.Lock()

# Domain handle: tests monkeypatch srv._domain
_domain: Any = None
try:
    from HDT_MCP.domain.services import HDTService
    from HDT_MCP.domain.ports import WalkSourcePort

    class _EmptyWalk(WalkSourcePort):
        def fetch_walk(self, user_id: int, *, from_iso=None, to_iso=None, limit=None, offset=None):
            return []

    _domain = HDTService(walk_source=_EmptyWalk(), vault=None)
except Exception:
    _domain = None


# -----------------------------
# Internal sync helpers
# -----------------------------

def _sync_policy_module() -> None:
    """
    Ensure the extracted policy module sees overrides patched on HDT_MCP.server.
    This is critical because tests patch srv._POLICY_OVERRIDE / srv._POLICY_PATH.
    """
    if hasattr(pol, "_POLICY_OVERRIDE"):
        pol._POLICY_OVERRIDE = _POLICY_OVERRIDE
    if hasattr(pol, "_POLICY_PATH"):
        pol._POLICY_PATH = _POLICY_PATH


# -----------------------------
# Telemetry wrappers (tests import these)
# -----------------------------

def _log_event(
    kind: str,
    name: str,
    args: dict | None = None,
    ok: bool = True,
    ms: int = 0,
    *,
    client_id: str | None = None,
    corr_id: str | None = None,
) -> None:
    # ensure telemetry writes to the same directory tests inspect
    os.environ["HDT_TELEMETRY_DIR"] = str(_TELEMETRY_DIR)
    tel.log_event(kind, name, args, ok, ms, client_id=client_id, corr_id=corr_id)


# -----------------------------
# Policy wrappers (tests import these)
# -----------------------------

def _policy_reset_cache() -> None:
    _sync_policy_module()
    # support either name depending on your extracted module version
    if hasattr(pol, "policy_reset_cache"):
        pol.policy_reset_cache()
    elif hasattr(pol, "_policy_reset_cache"):
        pol._policy_reset_cache()  # type: ignore[attr-defined]


def _policy_last_meta() -> dict:
    _sync_policy_module()
    if hasattr(pol, "policy_last_meta"):
        return pol.policy_last_meta()
    if hasattr(pol, "_policy_last_meta"):
        return pol._policy_last_meta()  # type: ignore[attr-defined]
    return {}


# Exported redaction helper expected by tests
def _redact_inplace(doc: object, paths: list[str]) -> int:
    _sync_policy_module()
    if hasattr(pol, "_redact_inplace"):
        return pol._redact_inplace(doc, paths)  # type: ignore[attr-defined]
    # fallback: minimal implementation
    total = 0
    for p in paths or []:
        if not isinstance(p, str) or not p:
            continue
        parts = p.split(".")

        def _walk(node: object, parts_: list[str]) -> int:
            if not parts_:
                return 0
            head, tail = parts_[0], parts_[1:]
            if isinstance(node, list):
                return sum(_walk(x, parts_) for x in node)
            if not isinstance(node, dict) or head not in node:
                return 0
            if not tail:
                node[head] = REDACT_TOKEN
                return 1
            return _walk(node[head], tail)

        total += _walk(doc, parts)
    return total


def _apply_policy(purpose: str, tool_name: str, payload: dict, *, client_id: str | None = None) -> dict:
    _sync_policy_module()
    return pol.apply_policy(purpose, tool_name, payload, client_id=client_id)


def _apply_policy_safe(purpose: str, tool_name: str, payload: dict, *, client_id: str | None = None) -> dict:
    _sync_policy_module()
    return pol.apply_policy_safe(purpose, tool_name, payload, client_id=client_id)


def _apply_policy_metrics(purpose: str, tool_name: str, payload: dict, *, client_id: str | None = None):
    _sync_policy_module()
    return pol.apply_policy_metrics(purpose, tool_name, payload, client_id=client_id)


def policy_evaluate(purpose: str = "analytics", client_id: str | None = None, tool: str | None = None) -> dict:
    """
    Small helper used by legacy tests. Returns effective rule (allow + redact list).
    """
    # Load policy from override or file
    if _POLICY_OVERRIDE is not None:
        pol_obj = _POLICY_OVERRIDE
    else:
        try:
            pol_obj = json.loads(_POLICY_PATH.read_text(encoding="utf-8"))
        except Exception:
            pol_obj = {}

    eff = (pol_obj.get("defaults", {}) or {}).get(purpose, {"allow": True, "redact": []})
    if client_id:
        eff = {**eff, **(((pol_obj.get("clients", {}) or {}).get(client_id, {}) or {}).get(purpose, {}))}
    if tool:
        eff = {**eff, **((((pol_obj.get("tools", {}) or {}).get(tool, {}) or {}).get(purpose, {})))}

    eff.setdefault("allow", True)
    eff.setdefault("redact", [])
    return {"purpose": purpose, "allow": bool(eff.get("allow", True)), "redact": eff.get("redact", [])}


# -----------------------------
# Minimal cached GET layer (used by tests via monkeypatch)
# -----------------------------

def _hdt_get(path: str, params: dict | None = None) -> dict:
    """
    Legacy backend fetcher. In unit tests, this is monkeypatched.
    In Option D production, you should not rely on this.
    """
    raise RuntimeError("_hdt_get is not configured. Tests should monkeypatch it.")


def _cached_get(path: str, params: dict | None = None) -> dict:
    key = (path, tuple(sorted((params or {}).items())))
    now = _time.time()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < _CACHE_TTL:
            return copy.deepcopy(hit[1])

    data = _hdt_get(path, params)
    with _cache_lock:
        _cache[key] = (now, copy.deepcopy(data))
    return copy.deepcopy(data)


# -----------------------------
# Legacy tool-like helpers referenced by policy tests
# -----------------------------

def tool_get_sugarvita_data(user_id: str) -> dict:
    raw = _cached_get("/get_sugarvita_data", {"user_id": user_id})
    return _apply_policy_safe("analytics", "hdt.get_sugarvita_data@v1", raw, client_id=None)


def tool_get_sugarvita_player_types(user_id: str, purpose: str = "analytics") -> dict:
    raw = _cached_get("/get_sugarvita_player_types", {"user_id": user_id})
    return _apply_policy_safe(purpose, "hdt.get_sugarvita_player_types@v1", raw, client_id=None)


# -----------------------------
# Walk stream helper expected by tests
# -----------------------------

def hdt_walk_stream(
    user_id: int,
    prefer: str = "auto",
    start: str | None = None,
    end: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> dict:
    """
    Legacy domain-shaped walk stream helper.

    - If srv._domain is monkeypatched (tests), we use it.
    - Otherwise we fall back to a minimal empty-domain implementation.
    - Applies analytics policy under tool name hdt.walk.stream@v1.
    """
    if prefer not in ("auto", "vault", "live"):
        return typed_error("bad_request", "prefer must be one of: auto, vault, live", prefer=prefer)

    prefer_vault = True if prefer in ("auto", "vault") else False

    view = None
    if _domain is not None:
        try:
            view = _domain.walk_stream(
                int(user_id),
                prefer_vault=prefer_vault,
                from_iso=start,
                to_iso=end,
                limit=limit,
                offset=offset,
            )
        except Exception:
            view = None

    # Build payload
    if view is None:
        payload = {"user_id": int(user_id), "records": [], "source": "none", "stats": {"days": 0, "total_steps": 0, "avg_steps": 0}}
        return _apply_policy_safe("analytics", "hdt.walk.stream@v1", payload, client_id=None)

    # records may be pydantic or dummy objects; support both
    recs = []
    for r in (getattr(view, "records", []) or []):
        if hasattr(r, "model_dump"):
            d = r.model_dump()
        else:
            d = {
                "date": getattr(r, "date", None),
                "steps": getattr(r, "steps", 0),
                "distance_meters": getattr(r, "distance_meters", None),
                "duration": getattr(r, "duration", None),
                "kcalories": getattr(r, "kcalories", None),
            }
        recs.append(d)

    stats_obj = getattr(view, "stats", None)
    if stats_obj is None:
        stats = {"days": len(recs), "total_steps": sum(int(x.get("steps") or 0) for x in recs), "avg_steps": 0}
    else:
        stats = {
            "days": getattr(stats_obj, "days", 0),
            "total_steps": getattr(stats_obj, "total_steps", 0),
            "avg_steps": getattr(stats_obj, "avg_steps", 0),
        }

    payload = {
        "user_id": int(user_id),
        "records": recs,
        "source": getattr(view, "source", "unknown"),
        "stats": stats,
    }
    return _apply_policy_safe("analytics", "hdt.walk.stream@v1", payload, client_id=None)
