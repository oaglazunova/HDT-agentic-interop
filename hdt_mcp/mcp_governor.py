from __future__ import annotations

import json
from typing import Any, Dict, Optional
import os
import time

from .sources_mcp_client import SourcesMCPClient
from hdt_mcp.observability.telemetry import log_event
from hdt_mcp.core.context import get_request_id
from hdt_mcp.core.errors import typed_error
from hdt_mcp import vault_store


def _as_json(obj: Any) -> Any:
    """Parse JSON text responses coming from MCP content."""
    if isinstance(obj, str):
        s = obj.strip()
        if s.startswith("{") or s.startswith("["):
            return json.loads(s)
    return obj

def _vault_try_read_walk(
    *,
    user_id: int,
    start_date: str | None,
    end_date: str | None,
    limit: int | None,
    offset: int | None,
    prefer_source: str,
    attempts: list[dict],
    label: str = "vault",
) -> dict | None:
    """
    Returns vault payload if it has records, else None.
    Always appends an attempt entry (ok True/False).
    """
    if not vault_store.enabled():
        attempts.append({"source": label, "ok": False, "error": {"code": "vault_disabled", "message": "Vault disabled"}})
        return None

    try:
        v = vault_store.fetch_walk(
            user_id=user_id,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            offset=offset,
            prefer_source=prefer_source,
        )
        if isinstance(v, dict) and v.get("records"):
            attempts.append({"source": label, "ok": True})
            return v

        attempts.append({"source": label, "ok": False, "error": {"code": "vault_empty", "message": "Vault has no walk records for this query"}})
        return None

    except Exception as e:
        attempts.append({"source": label, "ok": False, "error": {"code": "vault_read_failed", "message": str(e)}})
        return None


def _vault_try_write_walk(
    *,
    user_id: int,
    records: list[dict],
    source: str,
    attempts: list[dict],
) -> None:
    """
    Best-effort write-through. Never raises.
    """
    if not vault_store.enabled():
        return
    try:
        vault_store.upsert_walk(user_id, records or [], source=source)
    except Exception as e:
        attempts.append({"source": "vault_write", "ok": False, "error": {"code": "vault_write_failed", "message": str(e)}})


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
            prefer: str = "gamebus",
            prefer_data: str = "auto",
    ) -> Dict[str, Any]:
        t0 = time.perf_counter()

        # Args for Sources MCP tools (do NOT include 'prefer' / 'prefer_data')
        tool_args = {
            "user_id": user_id,
            "start_date": start_date,
            "end_date": end_date,
            "limit": limit,
            "offset": offset,
        }

        attempts: list[dict] = []
        selected_source: str | None = None
        result: Dict[str, Any] | None = None
        exc: str | None = None

        prefer_data_norm = (prefer_data or "auto").strip().lower()
        if prefer_data_norm not in {"auto", "vault", "live"}:
            result = typed_error(
                "bad_request",
                "prefer_data must be one of: auto, vault, live",
                user_id=user_id,
                prefer_data=prefer_data,
            )
            return result

        # 1) Vault-first (auto|vault)
        if prefer_data_norm in {"auto", "vault"}:
            v = _vault_try_read_walk(
                user_id=user_id,
                start_date=start_date,
                end_date=end_date,
                limit=limit,
                offset=offset,
                prefer_source=prefer,
                attempts=attempts,
                label="vault",
            )
            if v is not None:
                selected_source = "vault"
                v["selected_source"] = "vault"
                v["attempts"] = attempts
                result = v
                return result

        # Explicit vault-only request and vault had no data.
        if prefer_data_norm == "vault":
            result = typed_error(
                "vault_empty",
                "prefer_data=vault requested but vault had no matching data",
                user_id=user_id,
                details=attempts,
            )
            return result

        try:
            # Live sources
            order = ["gamebus", "googlefit"] if prefer.lower() == "gamebus" else ["googlefit", "gamebus"]

            for src in order:
                tool = f"source.{src}.walk.fetch@v1"
                raw = await self.sources.call_tool(tool, tool_args)
                payload = _as_json(raw)

                if isinstance(payload, dict) and "error" not in payload:
                    selected_source = src
                    attempts.append({"source": src, "ok": True})

                    # Best-effort write-through to vault
                    _vault_try_write_walk(
                        user_id=user_id,
                        records=payload.get("records", []),
                        source=src,
                        attempts=attempts,
                    )

                    payload["selected_source"] = src
                    payload["attempts"] = attempts
                    result = payload
                    break

                err = payload.get("error", {}) if isinstance(payload, dict) else {"code": "unknown",
                                                                                  "message": str(payload)}
                attempts.append({"source": src, "ok": False, "error": err})

            # Live failed => error result
            if result is None:
                result = {
                    "error": {
                        "code": "all_sources_failed",
                        "message": "All walk sources failed for this user/request.",
                        "details": attempts,
                    },
                    "user_id": user_id,
                }

                # 2) Auto fallback to vault if live failed
                if prefer_data_norm == "auto":
                    v = _vault_try_read_walk(
                        user_id=user_id,
                        start_date=start_date,
                        end_date=end_date,
                        limit=limit,
                        offset=offset,
                        prefer_source=prefer,
                        attempts=attempts,
                        label="vault_fallback",
                    )
                    if v is not None:
                        selected_source = "vault"
                        v["selected_source"] = "vault"
                        v["attempts"] = attempts
                        result = v

            return result

        except Exception as e:
            exc = str(e)
            raise

        finally:
            ms = int((time.perf_counter() - t0) * 1000)
            cid = os.getenv("MCP_CLIENT_ID", "MODEL_DEVELOPER_1")
            ok = bool(result) and isinstance(result, dict) and ("error" not in result)

            log_payload = {
                "user_id": user_id,
                "prefer": prefer,
                "prefer_data": prefer_data_norm,
                "selected_source": selected_source,
                "attempts": attempts,
            }
            if exc:
                log_payload["exception"] = exc

            log_event(
                "governor",
                "walk.fetch",
                log_payload,
                ok=ok,
                ms=ms,
                client_id=cid,
                corr_id=get_request_id(),
            )

    async def fetch_trivia(
            self,
            user_id: int,
            start_date: Optional[str] = None,
            end_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        t0 = time.perf_counter()
        cid = os.getenv("MCP_CLIENT_ID", "MODEL_DEVELOPER_1")

        args = {"user_id": user_id, "start_date": start_date, "end_date": end_date}
        result: Dict[str, Any] | None = None
        exc: str | None = None

        try:
            raw = await self.sources.call_tool("source.gamebus.trivia.fetch@v1", args)
            payload = _as_json(raw)

            if isinstance(payload, dict):
                result = payload
            else:
                result = {"error": {"code": "unknown", "message": str(payload)}, "user_id": user_id}

            return result

        except Exception as e:
            exc = str(e)
            raise

        finally:
            ms = int((time.perf_counter() - t0) * 1000)
            ok = bool(result) and isinstance(result, dict) and ("error" not in result)

            log_payload = {
                "user_id": user_id,
                "source": "gamebus",
                "tool": "source.gamebus.trivia.fetch@v1",
                "args": args,
            }
            if exc:
                log_payload["exception"] = exc

            log_event(
                "governor",
                "trivia.fetch",
                log_payload,
                ok=ok,
                ms=ms,
                client_id=cid,
                corr_id=get_request_id(),
            )

    async def fetch_sugarvita(
            self,
            user_id: int,
            start_date: Optional[str] = None,
            end_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        t0 = time.perf_counter()
        cid = os.getenv("MCP_CLIENT_ID", "MODEL_DEVELOPER_1")

        args = {"user_id": user_id, "start_date": start_date, "end_date": end_date}
        result: Dict[str, Any] | None = None
        exc: str | None = None

        try:
            raw = await self.sources.call_tool("source.gamebus.sugarvita.fetch@v1", args)
            payload = _as_json(raw)

            if isinstance(payload, dict):
                result = payload
            else:
                result = {"error": {"code": "unknown", "message": str(payload)}, "user_id": user_id}

            return result

        except Exception as e:
            exc = str(e)
            raise

        finally:
            ms = int((time.perf_counter() - t0) * 1000)
            ok = bool(result) and isinstance(result, dict) and ("error" not in result)

            log_payload = {
                "user_id": user_id,
                "source": "gamebus",
                "tool": "source.gamebus.sugarvita.fetch@v1",
                "args": args,
            }
            if exc:
                log_payload["exception"] = exc

            log_event(
                "governor",
                "sugarvita.fetch",
                log_payload,
                ok=ok,
                ms=ms,
                client_id=cid,
                corr_id=get_request_id(),
            )

