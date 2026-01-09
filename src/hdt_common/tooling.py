from __future__ import annotations

import inspect
import time
import functools
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from hdt_common.context import get_request_id, new_request_id, set_request_id
from hdt_common.errors import typed_error
from hdt_common.telemetry import log_event


# ---------------------------------------------------------------------------
# Shared helpers for MCP tool handlers
# ---------------------------------------------------------------------------


_REDACTION_KEYS = {"auth_bearer", "authorization", "token", "access_token", "api_key", "apikey"}


def sanitize_args_for_log(args: dict | None) -> dict:
    """Remove obvious secrets from args (telemetry layer also redacts)."""
    out: dict[str, Any] = {}
    for k, v in (args or {}).items():
        out[str(k)] = "***redacted***" if str(k).lower() in _REDACTION_KEYS else v
    return out


def _bound_args(fn: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
    """Bind positional/keyword args to parameter names for logging."""
    try:
        sig = inspect.signature(fn)
        bound = sig.bind_partial(*args, **kwargs)
        return dict(bound.arguments)
    except Exception:
        # Fallback: best effort
        d: dict[str, Any] = {}
        d.update(kwargs)
        if args:
            d["_args"] = list(args)
        return d


@dataclass(frozen=True)
class InstrumentConfig:
    kind: str
    name: str
    client_id: str
    telemetry_file: str = "mcp-telemetry.jsonl"

    # correlation id behavior
    new_corr_id_per_call: bool = False

    # attach corr_id to returned dict for debugging
    attach_corr_id: bool = True


def instrument_sync_tool(cfg: InstrumentConfig):
    """Decorator for sync tools (e.g., Sources MCP)."""

    def decorator(fn: Callable[..., Any]):
        fn_sig = inspect.signature(fn)

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any):
            # Ensure corr_id exists; Sources may already have one set via sources.context.set.v1
            corr_id = get_request_id()
            if cfg.new_corr_id_per_call or not corr_id:
                corr_id = new_request_id()
                set_request_id(corr_id)

            t0 = time.perf_counter()
            bound = _bound_args(fn, args, kwargs)
            args_for_log = {"args": sanitize_args_for_log(bound)}

            try:
                payload = fn(*args, **kwargs)
            except Exception as e:
                payload = typed_error("internal", str(e))

            ms = int((time.perf_counter() - t0) * 1000)
            ok = not (isinstance(payload, dict) and "error" in payload)
            if isinstance(payload, dict) and payload.get("error"):
                args_for_log["error"] = payload.get("error")

            log_event(
                cfg.kind,
                cfg.name,
                args_for_log,
                ok=ok,
                ms=ms,
                client_id=cfg.client_id,
                corr_id=corr_id,
                telemetry_file=cfg.telemetry_file,
            )

            if cfg.attach_corr_id and isinstance(payload, dict):
                payload.setdefault("corr_id", corr_id)
            return payload

        wrapper.__signature__ = fn_sig  # type: ignore[attr-defined]
        return wrapper

    return decorator


@dataclass(frozen=True)
class PolicyConfig:
    """Optional policy enforcement configuration for instrumented tools."""
    lanes: set[str]
    # policy engine hooks
    apply_policy: Callable[..., dict]
    apply_policy_safe: Callable[..., dict]
    policy_last_meta: Callable[[], dict | None]
    purpose_param: str = "purpose"


# uses existing helpers: get_request_id, new_request_id, set_request_id
# _bound_args, sanitize_args_for_log, typed_error, log_event
def instrument_async_tool(cfg: InstrumentConfig, *, policy: PolicyConfig | None = None):
    """Decorator for async tools (e.g., HDT MCP Option D)."""

    def decorator(fn: Callable[..., Awaitable[Any]]):
        fn_sig = inspect.signature(fn)

        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any):
            corr_id = get_request_id()
            if cfg.new_corr_id_per_call or not corr_id:
                corr_id = new_request_id()
                set_request_id(corr_id)

            t0 = time.perf_counter()

            # Bind for logging AND for robust purpose extraction
            bound = fn_sig.bind_partial(*args, **kwargs)
            bound.apply_defaults()

            args_for_log: dict[str, Any] = {"args": sanitize_args_for_log(dict(bound.arguments))}

            # Policy: validate purpose and pre-check deny
            purpose_value: str | None = None
            if policy is not None:
                raw_purpose = bound.arguments.get(policy.purpose_param, "")
                purpose_value = (str(raw_purpose) if raw_purpose is not None else "").strip().lower()
                args_for_log["purpose"] = purpose_value

                if purpose_value not in policy.lanes:
                    payload = typed_error(
                        "bad_request",
                        f"{policy.purpose_param} must be one of: {', '.join(sorted(policy.lanes))}",
                        **{policy.purpose_param: raw_purpose},
                    )
                    ms = int((time.perf_counter() - t0) * 1000)
                    args_for_log["error"] = payload.get("error")
                    log_event(cfg.kind, cfg.name, args_for_log, ok=False, ms=ms, client_id=cfg.client_id, corr_id=corr_id)
                    if cfg.attach_corr_id and isinstance(payload, dict):
                        payload.setdefault("corr_id", corr_id)
                    return payload

                # deny-fast: avoid downstream calls
                probe = policy.apply_policy(purpose_value, cfg.name, {}, client_id=cfg.client_id)
                if isinstance(probe, dict) and probe.get("error", {}).get("code") == "denied_by_policy":
                    ms = int((time.perf_counter() - t0) * 1000)
                    meta = policy.policy_last_meta() or {}
                    args_for_log["policy"] = meta
                    args_for_log["error"] = probe.get("error")
                    log_event(cfg.kind, cfg.name, args_for_log, ok=False, ms=ms, client_id=cfg.client_id, corr_id=corr_id)
                    if cfg.attach_corr_id and isinstance(probe, dict):
                        probe.setdefault("corr_id", corr_id)
                    return probe

            try:
                payload = await fn(*args, **kwargs)

                # Apply redaction only on successful payloads
                if policy is not None and isinstance(payload, dict) and "error" not in payload:
                    payload = policy.apply_policy_safe(purpose_value or "", cfg.name, payload, client_id=cfg.client_id)

            except Exception as e:
                # Consider: avoid leaking raw exception messages in production
                payload = typed_error("internal", str(e))

            ms = int((time.perf_counter() - t0) * 1000)
            ok = not (isinstance(payload, dict) and "error" in payload)

            if policy is not None:
                args_for_log["policy"] = policy.policy_last_meta() or {}

            if isinstance(payload, dict) and payload.get("error"):
                args_for_log["error"] = payload.get("error")

            log_event(cfg.kind, cfg.name, args_for_log, ok=ok, ms=ms, client_id=cfg.client_id, corr_id=corr_id)

            if cfg.attach_corr_id and isinstance(payload, dict):
                payload.setdefault("corr_id", corr_id)
            return payload

        # Preserve signature for schema generation
        wrapper.__signature__ = fn_sig  # type: ignore[attr-defined]
        return wrapper

    return decorator

