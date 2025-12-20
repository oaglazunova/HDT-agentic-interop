from __future__ import annotations

import os
from typing import Optional
import logging

from mcp.server.fastmcp import FastMCP
from hdt_mcp.mcp_governor import HDTGovernor
from hdt_mcp.policy.engine import apply_policy, apply_policy_safe, policy_last_meta
from hdt_mcp.core.tooling import (
    InstrumentConfig,
    PolicyConfig,
    instrument_async_tool,
    instrument_sync_tool,
)
from config.settings import init_runtime
from hdt_mcp.observability.telemetry import telemetry_recent
from hdt_mcp.policy.engine import explain_policy


logger = logging.getLogger(__name__)

mcp = FastMCP(
    name="HDT-MCP-OptionD",
    instructions="External-facing HDT MCP server (Option D). Delegates to HDTGovernor which calls Sources MCP.",
)

gov = HDTGovernor()

MCP_CLIENT_ID = os.getenv("MCP_CLIENT_ID", "MODEL_DEVELOPER_1")
LANES = {"analytics", "modeling", "coaching"}

_POLICY_CFG = PolicyConfig(
    lanes=LANES,
    apply_policy=apply_policy,
    apply_policy_safe=apply_policy_safe,
    policy_last_meta=policy_last_meta,
)

def _cfg(tool_name: str) -> InstrumentConfig:
    return InstrumentConfig(
        kind="tool",
        name=tool_name,
        client_id=MCP_CLIENT_ID,
        new_corr_id_per_call=True,
    )

def _instrument(tool_name: str):
    return instrument_async_tool(_cfg(tool_name), policy=_POLICY_CFG)


@mcp.tool(name="hdt.healthz@v1")
@instrument_sync_tool(_cfg("hdt.healthz@v1"))  # remove if you don't want telemetry for healthz
def hdt_healthz() -> dict:
    return {"ok": True}


@mcp.tool(name="hdt.sources.status@v1")
@_instrument("hdt.sources.status@v1")
async def hdt_sources_status(user_id: int, purpose: str = "analytics") -> dict:
    return await gov.sources_status(user_id)


@mcp.tool(name="hdt.walk.fetch@v1")
@_instrument("hdt.walk.fetch@v1")
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
    return await gov.fetch_walk(
        user_id=user_id,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        offset=offset,
        prefer=prefer,
        prefer_data=prefer_data,
        purpose=purpose,
    )


@mcp.tool(name="hdt.trivia.fetch@v1")
@_instrument("hdt.trivia.fetch@v1")
async def hdt_trivia_fetch(
    user_id: int,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    purpose: str = "analytics",
) -> dict:
    return await gov.fetch_trivia(user_id=user_id, start_date=start_date, end_date=end_date, purpose=purpose)


@mcp.tool(name="hdt.sugarvita.fetch@v1")
@_instrument("hdt.sugarvita.fetch@v1")
async def hdt_sugarvita_fetch(
    user_id: int,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    purpose: str = "analytics",
) -> dict:
    return await gov.fetch_sugarvita(user_id=user_id, start_date=start_date, end_date=end_date, purpose=purpose)


@mcp.tool(name="hdt.walk.features@v1")
@_instrument("hdt.walk.features@v1")
async def hdt_walk_features(
    user_id: int,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
    prefer: str = "gamebus",
    prefer_data: str = "auto",
    purpose: str = "modeling",
) -> dict:
    return await gov.walk_features(
        user_id=user_id,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        offset=offset,
        prefer=prefer,
        prefer_data=prefer_data,
        purpose=purpose,
    )


@mcp.tool(name="hdt.policy.explain@v1")
@_instrument("hdt.policy.explain@v1")
async def hdt_policy_explain(
    tool: str,
    purpose: str = "analytics",
) -> dict:
    return explain_policy(purpose, tool, client_id=MCP_CLIENT_ID)


@mcp.tool(name="hdt.telemetry.recent@v1")
@_instrument("hdt.telemetry.recent@v1")
async def hdt_telemetry_recent(
    n: int = 50,
    purpose: str = "analytics",
) -> dict:
    # purpose is accepted to satisfy lane validation + consistent auditing,
    # but telemetry is already redacted on read (secrets + PII).
    return telemetry_recent(n=n)

def main() -> None:
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    mcp.run(transport=transport)


if __name__ == "__main__":
    init_runtime()
    main()
