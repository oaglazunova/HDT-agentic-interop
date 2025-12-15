from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

from mcp import ClientSession
from mcp.client.stdio import stdio_client, StdioServerParameters


class SourcesMCPClient:
    """
    Minimal stdio MCP client that spawns the Sources MCP server and calls tools.
    Simple by design: starts a fresh session per call to avoid lifecycle complexity.
    Optimize later if needed (persistent session).
    """

    def __init__(self) -> None:
        self._server = StdioServerParameters(
            command="python",
            args=["-m", "HDT_SOURCES_MCP.server"],
            env={"MCP_TRANSPORT": "stdio"},
        )

    async def call_tool(self, tool_name: str, args: Dict[str, Any]) -> Any:
        async with stdio_client(self._server) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                res = await session.call_tool(tool_name, args)
                # Most MCP implementations return JSON as text content
                if getattr(res, "content", None):
                    # Return the first content item; you can extend this later
                    c0 = res.content[0]
                    return getattr(c0, "text", c0)
                return res

    async def list_tools(self) -> Any:
        async with stdio_client(self._server) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await session.list_tools()
