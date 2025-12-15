from __future__ import annotations

import os
from typing import Optional

from mcp.server.fastmcp import FastMCP

from HDT_MCP.mcp_governor import HDTGovernor

mcp = FastMCP(
    name="HDT-MCP-OptionD",
    instructions="External-facing HDT MCP server (Option D). Delegates to HDTGovernor which calls Sources MCP.",
)

gov = HDTGovernor()


@mcp.tool(name="hdt.healthz@v1")
def hdt_healthz() -> dict:
    return {"ok": True}


@mcp.tool(name="hdt.sources.status@v1")
async def hdt_sources_status(user_id: int) -> dict:
    return await gov.sources_status(user_id)


@mcp.tool(name="hdt.walk.fetch@v1")
async def hdt_walk_fetch(
    user_id: int,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
    prefer: str = "gamebus",
) -> dict:
    return await gov.fetch_walk(
        user_id=user_id,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        offset=offset,
        prefer=prefer,
    )

@mcp.tool(name="hdt.trivia.fetch@v1")
async def hdt_trivia_fetch(
    user_id: int,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> dict:
    return await gov.fetch_trivia(user_id=user_id, start_date=start_date, end_date=end_date)

@mcp.tool(name="hdt.sugarvita.fetch@v1")
async def hdt_sugarvita_fetch(
    user_id: int,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> dict:
    return await gov.fetch_sugarvita(user_id=user_id, start_date=start_date, end_date=end_date)

def main() -> None:
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    mcp.run(transport=transport)


if __name__ == "__main__":
    main()
