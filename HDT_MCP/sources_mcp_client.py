from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict
from mcp import ClientSession
from mcp.client.stdio import stdio_client, StdioServerParameters

from HDT_MCP.core.context import get_request_id, new_request_id
from HDT_MCP.core.context import get_request_id


class SourcesMCPClient:
    """
    Minimal stdio MCP client that spawns the Sources MCP server and calls tools.
    Starts a fresh session per call (simple, reliable).
    """

    def __init__(self) -> None:
        self._command = "python"
        self._args = ["-m", "HDT_SOURCES_MCP.server"]

        # Put sources telemetry in its own directory to avoid Windows file contention.
        repo_root = Path(__file__).resolve().parents[1]
        self._sources_telemetry_dir = str(repo_root / "HDT_SOURCES_MCP" / "telemetry")

    def _server_params(self) -> StdioServerParameters:
        # Use the corr_id already set by server_option_d wrapper; fallback if absent.
        corr_id = get_request_id() or new_request_id()

        # IMPORTANT: include the existing process environment so PATH/VENV etc remain intact.
        env = dict(os.environ)
        env["MCP_TRANSPORT"] = "stdio"
        env["HDT_CORR_ID"] = corr_id
        env["HDT_TELEMETRY_DIR"] = self._sources_telemetry_dir

        return StdioServerParameters(
            command=self._command,
            args=self._args,
            env=env,
        )


    async def call_tool(self, tool_name: str, args: Dict[str, Any]) -> Any:
        env = dict(os.environ)
        env["MCP_TRANSPORT"] = "stdio"

        corr_id = get_request_id()
        if corr_id:
            env["HDT_CORR_ID"] = corr_id

        server = StdioServerParameters(
            command="python",
            args=["-m", "HDT_SOURCES_MCP.server"],
            env=env,
        )

        async with stdio_client(server) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                res = await session.call_tool(tool_name, args)
                if getattr(res, "content", None):
                    c0 = res.content[0]
                    return getattr(c0, "text", c0)
                return res

    async def list_tools(self) -> Any:
        env = dict(os.environ)
        env["MCP_TRANSPORT"] = "stdio"

        corr_id = get_request_id()
        if corr_id:
            env["HDT_CORR_ID"] = corr_id

        server = StdioServerParameters(
            command="python",
            args=["-m", "HDT_SOURCES_MCP.server"],
            env=env,
        )

        async with stdio_client(server) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await session.list_tools()

