from __future__ import annotations

from typing import Iterable


REDACT_DEFAULT_TOKEN = "***redacted***"


def merge_rule(base: dict | None, override: dict | None) -> dict:
    out = dict(base or {})
    if override:
        out.update(override)
    out.setdefault("allow", True)
    out.setdefault("redact", [])
    return out


def resolve_rule(policy: dict, purpose: str, tool_name: str, client_id: str | None) -> dict:
    """Compute effective rule for given purpose/tool/client using a simple
    precedence model: defaults < client < tool.
    """
    pol = policy or {}
    eff = merge_rule({}, (pol.get("defaults", {}) or {}).get(purpose))
    if client_id:
        eff = merge_rule(eff, (pol.get("clients", {}) or {}).get(client_id, {}).get(purpose))
    eff = merge_rule(eff, (pol.get("tools", {}) or {}).get(tool_name, {}).get(purpose))
    return eff


def redact_inplace(doc: object, paths: Iterable[str], token: str = REDACT_DEFAULT_TOKEN) -> int:
    """Redact fields in-place by dotted paths. Returns number of fields redacted.

    Supports arrays: a path like "users.email" will redact that field on every
    element of the list under `users`.
    """
    total = 0
    for p in paths or []:
        parts = p.split(".")
        total += _redact_path(doc, parts, token)
    return total


def _redact_path(node: object, parts: list[str], token: str) -> int:
    if not parts:
        return 0
    key, rest = parts[0], parts[1:]

    if isinstance(node, list):
        c = 0
        for item in node:
            c += _redact_path(item, parts, token)
        return c

    if not isinstance(node, dict) or key not in node:
        return 0

    if not rest:
        node[key] = token
        return 1

    return _redact_path(node[key], rest, token)
