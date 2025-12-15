from __future__ import annotations

import json
from typing import Any, Dict, Optional

from .sources_mcp_client import SourcesMCPClient


def _as_json(obj: Any) -> Any:
    """Parse JSON text responses coming from MCP content."""
    if isinstance(obj, str):
        s = obj.strip()
        if s.startswith("{") or s.startswith("["):
            return json.loads(s)
    return obj


class HDTGovernor:
    """
    Governing orchestrator:
    - Calls Sources MCP tools
    - Applies selection + fallback rules
    - Returns one normalized envelope (still minimal at this stage)
    """

    def __init__(self) -> None:
        self.sources = SourcesMCPClient()

    async def sources_status(self, user_id: int) -> Dict[str, Any]:
        out = await self.sources.call_tool("sources.status@v1", {"user_id": user_id})
        return _as_json(out)

    async def fetch_walk(
        self,
        user_id: int,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        prefer: str = "gamebus",  # "gamebus" | "googlefit"
    ) -> Dict[str, Any]:
        """
        Negotiation rule (minimal):
        - Try preferred source first
        - If error (not_connected/missing_token/upstream_error), fallback to the other
        """

        args = {"user_id": user_id, "start_date": start_date, "end_date": end_date, "limit": limit, "offset": offset}

        status = await self.sources_status(user_id)
        walk_status = (status.get("walk") or {}) if isinstance(status, dict) else {}

        candidates = []
        for src in ("gamebus", "googlefit"):
            s = (walk_status.get(src) or {}) if isinstance(walk_status, dict) else {}
            if s.get("configured") and s.get("has_token"):
                candidates.append(src)

        if not candidates:
            return {
                "error": {"code": "no_usable_sources", "message": "No usable walk sources (configured + token) for this user."},
                "user_id": user_id,
            }

        if prefer.lower() in candidates:
            order = [prefer.lower()] + [s for s in candidates if s != prefer.lower()]
        else:
            order = candidates

        attempts = []
        for src in order:
            tool = f"source.{src}.walk.fetch@v1"
            raw = await self.sources.call_tool(tool, args)
            payload = _as_json(raw)

            # Normalize into a consistent shape
            if isinstance(payload, dict) and "error" not in payload:
                payload["selected_source"] = src
                payload["attempts"] = attempts + [{"source": src, "ok": True}]
                return payload

            err = payload.get("error", {}) if isinstance(payload, dict) else {"code": "unknown", "message": str(payload)}
            attempts.append({"source": src, "ok": False, "error": err})

        # If both failed, return a Governor-level error with details
        return {
            "error": {
                "code": "all_sources_failed",
                "message": "All walk sources failed for this user/request.",
                "details": attempts,
            },
            "user_id": user_id,
        }

    async def fetch_trivia(
        self,
        user_id: int,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        args = {"user_id": user_id, "start_date": start_date, "end_date": end_date}
        raw = await self.sources.call_tool("source.gamebus.trivia.fetch@v1", args)
        payload = _as_json(raw)
        return payload if isinstance(payload, dict) else {"error": {"code": "unknown", "message": str(payload)}, "user_id": user_id}

    async def fetch_sugarvita(
        self,
        user_id: int,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        args = {"user_id": user_id, "start_date": start_date, "end_date": end_date}
        raw = await self.sources.call_tool("source.gamebus.sugarvita.fetch@v1", args)
        payload = _as_json(raw)
        return payload if isinstance(payload, dict) else {"error": {"code": "unknown", "message": str(payload)}, "user_id": user_id}
