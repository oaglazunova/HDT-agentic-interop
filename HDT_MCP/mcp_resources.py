"""MCP resource registrations.

Resources are read-only context that agents can open.
We register resources via a function so `hdt_mcp.server` can stay a small,
loader-friendly entrypoint.
"""

from __future__ import annotations

import json
import time as _time
from pathlib import Path
from typing import Any, Callable, Iterable

from mcp.server.fastmcp import FastMCP

from .domain.services import HDTService
from .observability.telemetry import recent as telemetry_recent
from .policy_runtime import PolicyRuntime


def register_resources(
    mcp: FastMCP,
    *,
    config_dir: Path,
    telemetry_dir: Path,
    domain: HDTService,
    policy: PolicyRuntime,
    client_id: str,
    integrated_tool_name: str,
    tool_registry: Iterable[dict[str, Any]],
    log_event: Callable[..., None],
) -> None:
    """Attach resources to the MCP server."""

    @mcp.resource("hdt://{user_id}/sources")
    def list_sources(user_id: str) -> dict[str, Any]:
        """Expose connected sources for a user, based on config/users.json."""
        users_path = config_dir / "users.json"
        try:
            with users_path.open("r", encoding="utf-8") as f:
                root = json.load(f)
            items = root.get("users", []) if isinstance(root, dict) else []
            u = next((u for u in items if str(u.get("user_id")) == str(user_id)), None)
        except FileNotFoundError:
            u = None
        except Exception:
            u = None
        return {"user_id": user_id, "sources": (u or {}).get("connected_apps_walk_data", [])}

    @mcp.resource("registry://tools")
    def registry_tools() -> dict[str, Any]:
        return {"server": "HDT-MCP", "tools": list(tool_registry)}

    @mcp.resource("telemetry://recent/{n}")
    def resource_telemetry_recent(n: int = 50) -> dict[str, Any]:
        return telemetry_recent(telemetry_dir, n)

    @mcp.resource("vault://user/{user_id}/integrated")
    def get_integrated_view(user_id: str) -> dict[str, Any]:
        t0 = _time.time()
        purpose = "analytics"
        try:
            view = domain.integrated_view(int(user_id))
            if hasattr(view, "model_dump"):
                integrated: dict[str, Any] = view.model_dump()  # pydantic v2
            else:
                integrated = {
                    "user_id": view.user_id,
                    "streams": view.streams,
                    "generated_at": view.generated_at,
                }

            out = policy.apply_safe(purpose, integrated_tool_name, integrated, client_id=client_id)

            days = (
                out.get("streams", {})
                .get("walk", {})
                .get("stats", {})
                .get("days", 0)
                if isinstance(out, dict)
                else 0
            )

            log_event(
                "resource",
                f"vault://user/{user_id}/integrated",
                {"user_id": user_id, "purpose": purpose, "records": days},
                True,
                int((_time.time() - t0) * 1000),
            )
            return out
        except Exception as e:
            log_event(
                "resource",
                f"vault://user/{user_id}/integrated",
                {"user_id": user_id, "purpose": purpose, "error": str(e)},
                False,
                int((_time.time() - t0) * 1000),
            )
            return {"error": {"code": "internal", "message": str(e)}, "user_id": user_id}
