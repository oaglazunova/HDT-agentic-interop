import asyncio
import sys
from pathlib import Path

# Add repo root to sys.path so top-level packages (HDT_MCP, HDT_SOURCES_MCP, etc.) are importable
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from HDT_MCP.mcp_governor import HDTGovernor  # or: from HDT_MCP.governor import HDTGovernor


async def main():
    gov = HDTGovernor()

    print("\nGovernor: sources_status(user_id=1)")
    print(await gov.sources_status(1))

    print("\nGovernor: fetch_walk(user_id=1, limit=5) prefer=gamebus")
    print(await gov.fetch_walk(user_id=1, limit=5, prefer="gamebus"))


if __name__ == "__main__":
    asyncio.run(main())
