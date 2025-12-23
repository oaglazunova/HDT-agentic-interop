from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


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


def _benign_stdio_shutdown_error(exc: BaseException) -> bool:
    # anyio/mcp shutdown edge-case (seen with mcp==1.25.x):
    # "Attempted to exit cancel scope in a different task than it was entered in"
    s = str(exc)
    return "Attempted to exit" in s and "cancel scope" in s


async def main() -> None:
    repo = Path(__file__).resolve().parents[1]
    telemetry_path = repo / "artifacts" / "telemetry" / "mcp-telemetry.jsonl"
    telemetry_dir = os.getenv("HDT_TELEMETRY_DIR", str(telemetry_path.parent))

    print("\n=== Option D Walk Demo ===")
    print(f"Repo root: {repo}")
    print(f"Telemetry dir: {telemetry_dir}")

    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", "hdt_mcp.gateway"],
        env=dict(os.environ, MCP_TRANSPORT="stdio"),
    )

    try:
        async with stdio_client(server) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # 1) List tools
                tools = await session.list_tools()
                print("\nTOOLS:")
                for t in tools.tools:
                    print(f"- {t.name}")

                # 2) Sources status (local config check)
                print("\nCALL hdt.sources.status.v1(user_id=1):")
                out = await _call(session, "hdt.sources.status.v1", {"user_id": 1, "purpose": "analytics"})
                print(_pretty(out))

                # 3) Vault-only walk fetch (deterministic demo)
                print('\nCALL hdt.walk.fetch.v1(user_id=1, limit=5, prefer_data="vault")')
                out = await _call(
                    session,
                    "hdt.walk.fetch.v1",
                    {"user_id": 1, "limit": 5, "prefer": "gamebus", "prefer_data": "vault", "purpose": "analytics"},
                )
                print(_pretty(out))

                # 4) Auto walk fetch (negotiation + fallback)
                print('\nCALL hdt.walk.fetch.v1(user_id=1, limit=5, prefer_data="auto")')
                out = await _call(
                    session,
                    "hdt.walk.fetch.v1",
                    {"user_id": 1, "limit": 5, "prefer": "gamebus", "prefer_data": "auto", "purpose": "analytics"},
                )
                print(_pretty(out))
    except BaseExceptionGroup as eg:  # Python 3.11+
        if not _benign_stdio_shutdown_error(eg):
            raise
    except RuntimeError as e:
        if not _benign_stdio_shutdown_error(e):
            raise

    print("\nDemo complete.")
    print("Tip: open the telemetry JSONL and watch new lines appear for each tool call.")
    print(f"Telemetry file is typically under: {telemetry_dir}")


if __name__ == "__main__":
    asyncio.run(main())
