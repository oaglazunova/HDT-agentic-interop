"""Runtime policy loading + application.

This module centralizes the *runtime* concerns of policy:
- loading policy.json with a fast file-signature cache
- computing effective rules (defaults -> client -> tool)
- applying allow/deny and redaction
- exposing a small "last policy" metadata surface for telemetry/tests

It intentionally avoids @dataclass in case the importing environment uses a
non-standard module loader.
"""

from __future__ import annotations

import copy
import json
import threading
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Literal

from .policy_engine import merge_rule as _merge_rule
from .policy_engine import redact_inplace as _redact_inplace
from .policy_engine import resolve_rule as _resolve_rule


Purpose = Literal["analytics", "modeling", "coaching"]


def typed_error(code: str, message: str, *, details: dict | None = None, **extra: object) -> dict:
    """Standardized error envelope used by MCP tools/resources."""

    err: dict[str, Any] = {"error": {"code": code, "message": message}}
    if details:
        err["error"]["details"] = details
    if extra:
        err.update(extra)
    return err


class PolicyRuntime:
    """Lazy policy loader + applicator."""

    def __init__(
        self,
        *,
        policy_path: Path,
        user_permissions_path: Path,
        redact_token: str = "***redacted***",
    ) -> None:
        self._policy_path = policy_path
        self._user_perms_path = user_permissions_path
        self._redact_token = redact_token

        self._cache: dict[str, Any] | None = None
        self._sig: tuple[int, int] | None = None  # (st_mtime_ns, st_size)
        self._lock = threading.Lock()
        self._override: dict[str, Any] | None = None

        self._last: ContextVar[dict[str, Any]] = ContextVar(
            "policy_last",
            default={"redactions": 0, "allowed": True, "purpose": "", "tool": ""},
        )

    # ---------------- loading ----------------
    def set_override(self, policy: dict[str, Any] | None) -> None:
        """Test hook: force a policy object (disables disk reads)."""

        with self._lock:
            self._override = policy

    def reset_cache(self) -> None:
        with self._lock:
            self._cache = None
            self._sig = None

    def _load_file(self) -> dict[str, Any]:
        try:
            with self._policy_path.open("r", encoding="utf-8") as f:
                return json.load(f) or {}
        except FileNotFoundError:
            return {}

    def policy(self) -> dict[str, Any]:
        if self._override is not None:
            return self._override

        try:
            st = self._policy_path.stat()
        except FileNotFoundError:
            with self._lock:
                self._cache, self._sig = {}, None
            return {}

        sig = (st.st_mtime_ns, st.st_size)
        with self._lock:
            if self._cache is None or self._sig != sig:
                self._cache = self._load_file()
                self._sig = sig
            return self._cache or {}

    def load_user_permissions(self) -> dict[str, Any]:
        try:
            with self._user_perms_path.open("r", encoding="utf-8") as f:
                return json.load(f) or {}
        except FileNotFoundError:
            return {}

    # ---------------- rule computation ----------------
    def resolve_rule(self, purpose: Purpose, tool_name: str, client_id: str | None) -> dict[str, Any]:
        return _resolve_rule(self.policy(), purpose, tool_name, client_id)

    def evaluate(self, purpose: Purpose, client_id: str | None = None, tool: str | None = None) -> dict[str, Any]:
        """Return effective allow/redact for debugging."""

        pol = self.policy()
        eff = _merge_rule({}, (pol.get("defaults", {}) or {}).get(purpose))
        if client_id:
            eff = _merge_rule(eff, (pol.get("clients", {}) or {}).get(client_id, {}).get(purpose))
        if tool:
            eff = _merge_rule(eff, (pol.get("tools", {}) or {}).get(tool, {}).get(purpose))
        return {"purpose": purpose, "allow": bool(eff.get("allow", True)), "redact": eff.get("redact") or []}

    # ---------------- apply ----------------
    def last_meta(self) -> dict[str, Any]:
        return self._last.get()

    def apply(self, purpose: Purpose, tool_name: str, payload: dict[str, Any], *, client_id: str | None = None) -> dict[str, Any]:
        """Apply allow/deny + in-place redaction; mutates payload if allowed."""

        rule = self.resolve_rule(purpose, tool_name, client_id)
        if not rule.get("allow", True):
            self._last.set({"redactions": 0, "allowed": False, "purpose": purpose, "tool": tool_name})
            return typed_error(
                "denied_by_policy",
                "Access denied by policy",
                purpose=purpose,
                tool=tool_name,
            )

        paths = rule.get("redact") or []
        redactions = _redact_inplace(payload, paths, token=self._redact_token) if paths else 0
        self._last.set({"redactions": int(redactions), "allowed": True, "purpose": purpose, "tool": tool_name})
        return payload

    def apply_safe(self, purpose: Purpose, tool_name: str, payload: dict[str, Any], *, client_id: str | None = None) -> dict[str, Any]:
        """Deep-copy + apply to avoid mutating cached/shared objects."""

        clone = copy.deepcopy(payload)
        return self.apply(purpose, tool_name, clone, client_id=client_id)

