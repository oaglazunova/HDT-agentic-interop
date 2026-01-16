
import asyncio
import os
import sys
from pathlib import Path

# Add src to sys.path
_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "src"))

from mcp import ClientSession
from mcp.client.stdio import stdio_client, StdioServerParameters

async def main():
    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", "hdt_sources_mcp.server"],
        env=dict(os.environ, MCP_TRANSPORT="stdio", HDT_DISABLE_TELEMETRY="1")
    )

    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print("Initialized")
            res = await session.call_tool("healthz.v1", {})
            print(f"Healthz: {res}")
            res = await session.call_tool("sources.status.v1", {"user_id": 1})
            print(f"Status: {res}")

if __name__ == "__main__":
    asyncio.run(main())
