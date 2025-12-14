"""MCP tool registrations.

Tools are callables with typed parameters; FastMCP uses signatures to
build JSON Schemas.

We register tools inside a function so server.py remains minimal.
"""

from __future__ import annotations

import time as _time
from typing import Any, Literal, TypedDict, Callable

from mcp.server.fastmcp import FastMCP

from .constants import LANE_ANALYTICS, LANE_MODELING, LANE_COACHING
from .domain.services import HDTService
from .models.behavior import behavior_strategy
from .policy_runtime import PolicyRuntime

Purpose = Literal["analytics", "modeling", "coaching"]


def _typed_error(code: str, message: str, *, details: dict | None = None, **extra: Any) -> dict[str, Any]:
    err: dict[str, Any] = {"error": {"code": code, "message": message}}
    if details:
        err["error"]["details"] = details
    if extra:
        err.update(extra)
    return err


class TimingPlan(TypedDict):
    next_window_local: str
    rationale: str


def register_tools(
    mcp: FastMCP,
    *,
    domain: HDTService,
    cached_get: Callable[[str, dict | None], dict[str, Any]],
    policy: PolicyRuntime,
    client_id: str,
    log_event: Callable[..., None],
    vault: Any | None,
    vault_enabled: bool,
    enable_policy_tools: bool,
    retryable_health_check: Callable[[], dict[str, Any]] | None = None,
) -> None:
    """Attach tools to the MCP server."""

    @mcp.tool(name="healthz@v1")
    def tool_healthz() -> dict[str, Any]:
        return (retryable_health_check() if retryable_health_check else {"ok": True})

    @mcp.tool(name="hdt.get_trivia_data@v1")
    def tool_get_trivia_data(user_id: str, purpose: Purpose = LANE_ANALYTICS) -> dict[str, Any]:
        t0 = _time.time()
        try:
            raw = cached_get("/get_trivia_data", {"user_id": user_id})
            out = policy.apply_safe(purpose, "hdt.get_trivia_data@v1", raw, client_id=client_id)
            meta = policy.last_meta()
            log_event(
                "tool",
                "hdt.get_trivia_data@v1",
                {"user_id": user_id, "purpose": purpose, "redactions": meta.get("redactions", 0)},
                True,
                int((_time.time() - t0) * 1000),
            )
            return out
        except Exception as e:
            log_event(
                "tool",
                "hdt.get_trivia_data@v1",
                {"user_id": user_id, "purpose": purpose, "error": str(e)},
                False,
                int((_time.time() - t0) * 1000),
            )
            return _typed_error("internal", str(e), user_id=user_id)

    @mcp.tool(name="hdt.get_sugarvita_data@v1")
    def tool_get_sugarvita_data(user_id: str, purpose: Purpose = LANE_ANALYTICS) -> dict[str, Any]:
        t0 = _time.time()
        try:
            raw = cached_get("/get_sugarvita_data", {"user_id": user_id})
            out = policy.apply_safe(purpose, "hdt.get_sugarvita_data@v1", raw, client_id=client_id)
            meta = policy.last_meta()
            log_event(
                "tool",
                "hdt.get_sugarvita_data@v1",
                {"user_id": user_id, "purpose": purpose, "redactions": meta.get("redactions", 0)},
                True,
                int((_time.time() - t0) * 1000),
            )
            return out
        except Exception as e:
            log_event(
                "tool",
                "hdt.get_sugarvita_data@v1",
                {"user_id": user_id, "purpose": purpose, "error": str(e)},
                False,
                int((_time.time() - t0) * 1000),
            )
            return _typed_error("internal", str(e), user_id=user_id)

    @mcp.tool(name="hdt.get_sugarvita_player_types@v1")
    def tool_get_sugarvita_player_types(user_id: str, purpose: Purpose = LANE_ANALYTICS) -> dict[str, Any]:
        t0 = _time.time()
        try:
            raw = cached_get("/get_sugarvita_player_types", {"user_id": user_id})
            out = policy.apply_safe(purpose, "hdt.get_sugarvita_player_types@v1", raw, client_id=client_id)
            meta = policy.last_meta()
            log_event(
                "tool",
                "hdt.get_sugarvita_player_types@v1",
                {"user_id": user_id, "purpose": purpose, "redactions": meta.get("redactions", 0)},
                True,
                int((_time.time() - t0) * 1000),
            )
            return out
        except Exception as e:
            log_event(
                "tool",
                "hdt.get_sugarvita_player_types@v1",
                {"user_id": user_id, "purpose": purpose, "error": str(e)},
                False,
                int((_time.time() - t0) * 1000),
            )
            return _typed_error("internal", str(e), user_id=user_id)

    @mcp.tool(name="hdt.get_health_literacy_diabetes@v1")
    def tool_get_health_literacy_diabetes(user_id: str, purpose: Purpose = LANE_ANALYTICS) -> dict[str, Any]:
        t0 = _time.time()
        try:
            raw = cached_get("/get_health_literacy_diabetes", {"user_id": user_id})
            out = policy.apply_safe(purpose, "hdt.get_health_literacy_diabetes@v1", raw, client_id=client_id)
            meta = policy.last_meta()
            log_event(
                "tool",
                "hdt.get_health_literacy_diabetes@v1",
                {"user_id": user_id, "purpose": purpose, "redactions": meta.get("redactions", 0)},
                True,
                int((_time.time() - t0) * 1000),
            )
            return out
        except Exception as e:
            log_event(
                "tool",
                "hdt.get_health_literacy_diabetes@v1",
                {"user_id": user_id, "purpose": purpose, "error": str(e)},
                False,
                int((_time.time() - t0) * 1000),
            )
            return _typed_error("internal", str(e), user_id=user_id)

    @mcp.tool(name="behavior_strategy@v1")
    def tool_behavior_strategy(user_id: str, purpose: Purpose = LANE_COACHING) -> dict[str, Any]:
        t0 = _time.time()
        try:
            plan = behavior_strategy(int(user_id))
            out = policy.apply_safe(purpose, "behavior_strategy@v1", plan, client_id=client_id)
            meta = policy.last_meta()
            log_event(
                "tool",
                "behavior_strategy@v1",
                {"user_id": user_id, "purpose": purpose, "redactions": meta.get("redactions", 0)},
                True,
                int((_time.time() - t0) * 1000),
            )
            return out
        except Exception as e:
            log_event(
                "tool",
                "behavior_strategy@v1",
                {"user_id": user_id, "purpose": purpose, "error": str(e)},
                False,
                int((_time.time() - t0) * 1000),
            )
            return _typed_error("internal", str(e), user_id=user_id)

    @mcp.tool(name="hdt.walk.stream@v1")
    def hdt_walk_stream(
        user_id: int,
        prefer: str = "auto",
        start: str | None = None,
        end: str | None = None,
        purpose: Purpose = LANE_ANALYTICS,
    ) -> dict[str, Any]:
        if prefer not in ("auto", "vault", "live"):
            return _typed_error("bad_request", "prefer must be one of: auto, vault, live", prefer=prefer)

        prefer_vault = True if prefer in ("auto", "vault") else False
        view = domain.walk_stream(int(user_id), prefer_vault=prefer_vault, from_iso=start, to_iso=end)

        payload = {
            "user_id": int(user_id),
            "records": [
                {
                    "date": r.date,
                    "steps": r.steps,
                    "distance_meters": r.distance_meters,
                    "duration": r.duration,
                    "kcalories": r.kcalories,
                }
                for r in view.records
            ],
            "source": view.source,
            "stats": view.stats.model_dump() if hasattr(view.stats, "model_dump") else {
                "days": view.stats.days,
                "total_steps": view.stats.total_steps,
                "avg_steps": view.stats.avg_steps,
            },
        }
        return policy.apply_safe(purpose, "hdt.walk.stream@v1", payload, client_id=client_id)

    @mcp.tool(name="hdt.walk.stats@v1")
    def hdt_walk_stats(
        user_id: int,
        start: str | None = None,
        end: str | None = None,
        purpose: Purpose = LANE_ANALYTICS,
    ) -> dict[str, Any]:
        view = domain.walk_stream(int(user_id), prefer_vault=True, from_iso=start, to_iso=end)
        stats = view.stats.model_dump() if hasattr(view.stats, "model_dump") else {
            "days": view.stats.days,
            "total_steps": view.stats.total_steps,
            "avg_steps": view.stats.avg_steps,
        }
        return policy.apply_safe(purpose, "hdt.walk.stats@v1", {"user_id": int(user_id), "stats": stats}, client_id=client_id)

    @mcp.tool(name="intervention_time@v1")
    def intervention_time(
        local_tz: str = "Europe/Amsterdam",
        preferred_hours: tuple[int, int] = (18, 21),
        min_gap_hours: int = 6,
        last_prompt_iso: str | None = None,
    ) -> TimingPlan:
        start_hour, end_hour = preferred_hours
        return {
            "next_window_local": f"today {start_hour:02d}:00–{end_hour:02d}:00 {local_tz}",
            "rationale": f"Respect ≥{min_gap_hours}h gap; evening adherence tendency.",
        }

    # --- policy tools (optional) ---
    if enable_policy_tools:

        @mcp.tool(name="policy.evaluate@v1")
        def policy_evaluate(
            purpose: Purpose = LANE_ANALYTICS,
            client_id_override: str | None = None,
            tool: str | None = None,
        ) -> dict[str, Any]:
            cid = client_id_override or client_id
            eff = policy.evaluate(purpose, tool_name=(tool or ""), client_id=cid)
            return {"purpose": purpose, "client_id": cid, "tool": tool, **eff}

        @mcp.tool(name="consent.status@v1")
        def consent_status(client_id_override: str | None = None) -> dict[str, Any]:
            cid = client_id_override or client_id
            perms = policy.load_user_permissions()
            users: list[dict[str, Any]] = []
            for uid, p in (perms or {}).items():
                allowed = (p.get("allowed_clients") or {}).get(cid, [])
                try:
                    users.append({"user_id": int(uid), "allowed_permissions": sorted(set(allowed))})
                except Exception:
                    users.append({"user_id": uid, "allowed_permissions": sorted(set(allowed))})
            return {"client_id": cid, "users": users}

        @mcp.tool(name="policy.reload@v1")
        def policy_reload() -> dict[str, Any]:
            policy.reset_cache()
            _ = policy.get_policy()
            return {"reloaded": True}

    # --- vault maintenance (optional) ---
    @mcp.tool(name="vault.maintain@v1")
    def vault_maintain(days: int = 60) -> dict[str, Any]:
        if not (vault and vault_enabled):
            return _typed_error("vault_disabled", "Vault is disabled", kept_last_days=days, deleted_rows=0)
        deleted = 0
        if hasattr(vault, "retain_last_days"):
            deleted = int(vault.retain_last_days(days))
        if hasattr(vault, "compact"):
            vault.compact()
        return {"kept_last_days": days, "deleted_rows": deleted}
