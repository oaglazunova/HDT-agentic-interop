from __future__ import annotations

from typing import Any

REDACT_TOKEN = "***redacted***"


def typed_error(code: str, message: str, *, details: dict | None = None, **extra: Any) -> dict:
    """
    Standard error envelope:
      {"error": {"code": code, "message": message, "details": {...}}, ...extra}
    """
    err: dict[str, Any] = {"error": {"code": code, "message": message}}
    if details:
        err["error"]["details"] = details
    if extra:
        err.update(extra)
    return err
