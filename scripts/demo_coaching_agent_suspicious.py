"""Demo: a (misbehaving) coaching agent that repeatedly attempts an analytics-only tool.

Purpose
-------
This script is intentionally 'bad': it calls an analytics tool with purpose=coaching,
which (under the guardian demo policy) should be denied. Those denied calls are still
useful because they leave an auditable trace in telemetry.

Usage (bash)
------------
export HDT_POLICY_PATH=config/policy.guardian_demo.json
export HDT_TELEMETRY_SUBJECT_SALT=demo-salt
export MCP_CLIENT_ID=COACHING_AGENT
python scripts/demo_coaching_agent_suspicious.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

_THIS_FILE = Path(__file__).resolve()
_REPO_ROOT = _THIS_FILE.parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _pretty(x: Any) -> str:
    try:
        return json.dumps(x, indent=2, ensure_ascii=False)
    except Exception:
        return str(x)


def _unwrap_tool_result(res: Any) -> Any:
    content = getattr(res, "content", None)
    if not content:
        return res
    c0 = content[0]
    if isinstance(c0, dict) and "text" in c0:
        return c0["text"]
    return getattr(c0, "text", c0)


async def main() -> int:
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    gateway_module = os.getenv("HDT_GATEWAY_MODULE", "hdt_mcp.gateway")
    python_cmd = os.getenv("MCP_PYTHON") or sys.executable

    user_id = int(os.getenv("HDT_SMOKE_USER_ID", "1"))
    tool_name = os.getenv("HDT_SUSPICIOUS_TOOL", "hdt.walk.fetch.v1")
    attempts = int(os.getenv("HDT_SUSPICIOUS_ATTEMPTS", "5"))

    print(f"[coaching-agent] Repo root: {_REPO_ROOT}")
    print(f"[coaching-agent] Gateway module: {gateway_module}")
    print(f"[coaching-agent] MCP_CLIENT_ID={os.getenv('MCP_CLIENT_ID')}")
    print(f"[coaching-agent] Policy: {os.getenv('HDT_POLICY_PATH')}")
    print(f"[coaching-agent] Attempts: {attempts} calls to {tool_name} with purpose=coaching")

    server = StdioServerParameters(
        command=python_cmd,
        args=["-m", gateway_module],
        env=dict(os.environ, MCP_TRANSPORT="stdio"),
    )

    denies = 0

    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            for i in range(1, attempts + 1):
                res = await session.call_tool(tool_name, {"user_id": user_id, "purpose": "coaching"})
                out = _unwrap_tool_result(res)
                if isinstance(out, str) and out.strip().startswith("{"):
                    try:
                        out = json.loads(out)
                    except Exception:
                        pass

                code = None
                if isinstance(out, dict) and isinstance(out.get("error"), dict):
                    code = out["error"].get("code")
                if code in {"denied_by_policy", "denied"}:
                    denies += 1

                print(f"\n[coaching-agent] call {i}/{attempts}: {tool_name} -> error_code={code}")
                if isinstance(out, dict):
                    # Keep the output short but traceable
                    snippet = {"error": out.get("error"), "corr_id": out.get("corr_id")}
                    print(_pretty(snippet))
                else:
                    print(_pretty(out))

    print(f"\n[coaching-agent] Done. Denied calls: {denies}/{attempts} (expected under guardian demo policy).")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
