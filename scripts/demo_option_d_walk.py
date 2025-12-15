from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import stdio_client, StdioServerParameters


def _pretty(x) -> str:
    if isinstance(x, str):
        try:
            return json.dumps(json.loads(x), indent=2, ensure_ascii=False)
        except Exception:
            return x
    return json.dumps(x, indent=2, ensure_ascii=False)


async def _call(session: ClientSession, name: str, args: dict):
    res = await session.call_tool(name, args)
    if getattr(res, "content", None):
        c0 = res.content[0]
        return getattr(c0, "text", c0)
    return res


async def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    telemetry_path = repo_root / "HDT_MCP" / "observability" / "telemetry" / "mcp-telemetry.jsonl"
    telemetry_dir = os.getenv("HDT_TELEMETRY_DIR", str(telemetry_path.parent))

    print("\n=== Option D Walk Demo ===")
    print(f"Repo root: {repo_root}")
    print(f"Telemetry dir: {telemetry_dir}")

    server = StdioServerParameters(
        command="python",
        args=["-m", "HDT_MCP.server_option_d"],
        env=dict(os.environ, MCP_TRANSPORT="stdio"),
    )

    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # 1) List tools
            tools = await session.list_tools()
            print("\nTOOLS:")
            for t in tools.tools:
                print(f"- {t.name}")

            # 2) Sources status (local config check)
            print("\nCALL hdt.sources.status@v1(user_id=1):")
            out = await _call(session, "hdt.sources.status@v1", {"user_id": 1, "purpose": "analytics"})
            print(_pretty(out))

            # 3) Vault-only walk fetch (deterministic demo)
            print('\nCALL hdt.walk.fetch@v1(user_id=1, limit=5, prefer_data="vault"):')
            out = await _call(
                session,
                "hdt.walk.fetch@v1",
                {"user_id": 1, "limit": 5, "prefer": "gamebus", "prefer_data": "vault", "purpose": "analytics"},
            )
            print(_pretty(out))

            # 4) Auto walk fetch (negotiation + fallback)
            print('\nCALL hdt.walk.fetch@v1(user_id=1, limit=5, prefer_data="auto"):')
            out = await _call(
                session,
                "hdt.walk.fetch@v1",
                {"user_id": 1, "limit": 5, "prefer": "gamebus", "prefer_data": "auto", "purpose": "analytics"},
            )
            print(_pretty(out))

    print("\nDemo complete.")
    print("Tip: open the telemetry JSONL and watch new lines appear for each tool call.")
    print(f"Telemetry file is typically under: {telemetry_dir}")


if __name__ == "__main__":
    asyncio.run(main())
