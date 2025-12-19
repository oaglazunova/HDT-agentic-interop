from __future__ import annotations

import json
import os
import sys

import pytest

pytest.importorskip("mcp")
from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp import ClientSession


def _unwrap_json(res) -> dict:
    # FastMCP/mcp typically returns a CallToolResult with a content list.
    content = getattr(res, "content", None)
    if content:
        c0 = content[0]
        if isinstance(c0, dict) and "text" in c0:
            return json.loads(c0["text"])
        text = getattr(c0, "text", None)
        if isinstance(text, str):
            return json.loads(text)
    # Fallback if a dict is returned directly
    if isinstance(res, dict):
        return res
    raise AssertionError(f"Unexpected tool result shape: {type(res)} {res!r}")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_hdt_mcp_gateway_healthz_and_tools(tmp_path):
    env = dict(os.environ)
    env["MCP_TRANSPORT"] = "stdio"
    env["HDT_TELEMETRY_DIR"] = str(tmp_path / "telemetry")

    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", "hdt_mcp.gateway"],
        env=env,
    )

    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            tool_names = [t.name for t in tools.tools]
            assert "hdt.healthz@v1" in tool_names

            for expected in ['hdt.trivia.fetch@v1', 'hdt.sugarvita.fetch@v1']:
                assert expected in tool_names

            res = await session.call_tool("hdt.healthz@v1", {})
            payload = _unwrap_json(res)
            assert payload.get("ok") is True
