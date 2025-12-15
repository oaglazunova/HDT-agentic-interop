from __future__ import annotations

import os
from typing import Optional, Callable, Awaitable
import time
from pathlib import Path
from dotenv import load_dotenv

from mcp.server.fastmcp import FastMCP

from HDT_MCP.mcp_governor import HDTGovernor
from HDT_MCP.policy.engine import apply_policy, apply_policy_safe, policy_last_meta
from HDT_MCP.observability.telemetry import log_event
from HDT_MCP.core.errors import typed_error
from HDT_MCP.core.context import new_request_id, set_request_id


# Load .env from repo root (works even when server is spawned as a subprocess)
_REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_REPO_ROOT / ".env", override=False)

mcp = FastMCP(
    name="HDT-MCP-OptionD",
    instructions="External-facing HDT MCP server (Option D). Delegates to HDTGovernor which calls Sources MCP.",
)

gov = HDTGovernor()

MCP_CLIENT_ID = os.getenv("MCP_CLIENT_ID", "MODEL_DEVELOPER_1")
LANES = {"analytics", "modeling", "coaching"}

def _sanitize_args(d: dict) -> dict:
    # Avoid logging anything token-like
    redaction_keys = {"auth_bearer", "authorization", "token", "access_token", "api_key", "apikey"}
    out = {}
    for k, v in (d or {}).items():
        out[k] = "***redacted***" if str(k).lower() in redaction_keys else v
    return out


async def _run_instrumented_tool(
    *,
    tool_name: str,
    purpose: str,
    args_for_log: dict,
    fn: Callable[[], Awaitable[dict]],
) -> dict:
    # Correlation ID per tool call
    corr_id = new_request_id()
    set_request_id(corr_id)

    t0 = time.perf_counter()

    # Validate purpose
    p = (purpose or "").strip().lower()
    if p not in LANES:
        ms = int((time.perf_counter() - t0) * 1000)
        out = typed_error("bad_request", "purpose must be one of: analytics, modeling, coaching", purpose=purpose)
        log_event(
            "tool",
            tool_name,
            {"args": _sanitize_args(args_for_log), "purpose": purpose},
            ok=False,
            ms=ms,
            client_id=MCP_CLIENT_ID,
            corr_id=corr_id,
        )
        return out

    # Policy pre-check: deny fast (avoid governor/sources)
    probe = apply_policy(p, tool_name, {}, client_id=MCP_CLIENT_ID)
    if isinstance(probe, dict) and probe.get("error", {}).get("code") == "denied_by_policy":
        ms = int((time.perf_counter() - t0) * 1000)
        meta = policy_last_meta()
        log_event(
            "tool",
            tool_name,
            {"args": _sanitize_args(args_for_log), "purpose": p, "policy": meta},
            ok=False,
            ms=ms,
            client_id=MCP_CLIENT_ID,
            corr_id=corr_id,
        )
        # Return deny error; do not call downstream
        return probe

    try:
        payload = await fn()

        # Apply redaction only on successful payloads
        if isinstance(payload, dict) and "error" not in payload:
            payload = apply_policy_safe(p, tool_name, payload, client_id=MCP_CLIENT_ID)

        ms = int((time.perf_counter() - t0) * 1000)
        meta = policy_last_meta()
        ok = not (isinstance(payload, dict) and "error" in payload)

        log_event(
            "tool",
            tool_name,
            {"args": _sanitize_args(args_for_log), "purpose": p, "policy": meta},
            ok=ok,
            ms=ms,
            client_id=MCP_CLIENT_ID,
            corr_id=corr_id,
        )

        # Optional: attach corr_id for debugging (safe, no PII)
        if isinstance(payload, dict):
            payload.setdefault("corr_id", corr_id)

        return payload

    except Exception as e:
        ms = int((time.perf_counter() - t0) * 1000)
        log_event(
            "tool",
            tool_name,
            {"args": _sanitize_args(args_for_log), "purpose": p, "exception": str(e)},
            ok=False,
            ms=ms,
            client_id=MCP_CLIENT_ID,
            corr_id=corr_id,
        )
        return typed_error("internal", str(e))


@mcp.tool(name="hdt.healthz@v1")
def hdt_healthz() -> dict:
    return {"ok": True}


@mcp.tool(name="hdt.sources.status@v1")
async def hdt_sources_status(user_id: int, purpose: str = "analytics") -> dict:
    tool_name = "hdt.sources.status@v1"
    return await _run_instrumented_tool(
        tool_name=tool_name,
        purpose=purpose,
        args_for_log={"user_id": user_id},
        fn=lambda: gov.sources_status(user_id),
    )


@mcp.tool(name="hdt.walk.fetch@v1")
async def hdt_walk_fetch(
    user_id: int,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
    prefer: str = "gamebus",
    prefer_data: str = "auto",
    purpose: str = "analytics",
) -> dict:
    tool_name = "hdt.walk.fetch@v1"
    args = {"user_id": user_id, "start_date": start_date, "end_date": end_date, "limit": limit, "offset": offset, "prefer": prefer, "prefer_data": prefer_data}
    return await _run_instrumented_tool(
        tool_name=tool_name,
        purpose=purpose,
        args_for_log=args,
        fn=lambda: gov.fetch_walk(user_id=user_id, start_date=start_date, end_date=end_date, limit=limit, offset=offset, prefer=prefer, prefer_data=prefer_data),
    )


@mcp.tool(name="hdt.trivia.fetch@v1")
async def hdt_trivia_fetch(
    user_id: int,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    purpose: str = "analytics",
) -> dict:
    tool_name = "hdt.trivia.fetch@v1"
    args = {"user_id": user_id, "start_date": start_date, "end_date": end_date}
    return await _run_instrumented_tool(
        tool_name=tool_name,
        purpose=purpose,
        args_for_log=args,
        fn=lambda: gov.fetch_trivia(user_id=user_id, start_date=start_date, end_date=end_date),
    )


@mcp.tool(name="hdt.sugarvita.fetch@v1")
async def hdt_sugarvita_fetch(
    user_id: int,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    purpose: str = "analytics",
) -> dict:
    tool_name = "hdt.sugarvita.fetch@v1"
    args = {"user_id": user_id, "start_date": start_date, "end_date": end_date}
    return await _run_instrumented_tool(
        tool_name=tool_name,
        purpose=purpose,
        args_for_log=args,
        fn=lambda: gov.fetch_sugarvita(user_id=user_id, start_date=start_date, end_date=end_date),
    )


def main() -> None:
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    mcp.run(transport=transport)


if __name__ == "__main__":
    main()
