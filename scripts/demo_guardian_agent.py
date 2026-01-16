"""Demo: Guardian agent (auditor) that queries telemetry for suspicious patterns.

Concept
-------
The guardian agent is a simple monitoring agent that uses the MCP tool
`hdt.telemetry.query.v1` to detect suspicious patterns, e.g. repeated
policy-denied attempts by another agent.

Importantly, this demo does not require direct file access: the telemetry store is
exposed as a tool, reducing the barrier to building governance/monitoring agents.

Usage (bash)
------------
# 1) (In one terminal) generate suspicious attempts:
export HDT_POLICY_PATH=config/policy.guardian_demo.json
export HDT_TELEMETRY_SUBJECT_SALT=demo-salt
export MCP_CLIENT_ID=COACHING_AGENT
python scripts/demo_coaching_agent_suspicious.py

# 2) (In another terminal) run the guardian:
export HDT_POLICY_PATH=config/policy.guardian_demo.json
export HDT_TELEMETRY_SUBJECT_SALT=demo-salt
export MCP_CLIENT_ID=GUARDIAN_AGENT
python scripts/demo_guardian_agent.py

Exit codes:
  0: no suspicious pattern detected
  3: suspicious pattern detected
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

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


def _coerce_json(out: Any) -> Any:
    if isinstance(out, str) and out.strip().startswith("{"):
        try:
            return json.loads(out)
        except Exception:
            return out
    return out


async def main() -> int:
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    gateway_module = os.getenv("HDT_GATEWAY_MODULE", "hdt_mcp.gateway")
    python_cmd = os.getenv("MCP_PYTHON") or sys.executable

    watch_client = os.getenv("HDT_GUARDIAN_WATCH_CLIENT", "COACHING_AGENT")
    lookback_s = int(os.getenv("HDT_GUARDIAN_LOOKBACK_S", "3600"))
    min_denies = int(os.getenv("HDT_GUARDIAN_MIN_DENIES", "3"))

    # This is the suspicious pattern we look for in this demo.
    denied_code = os.getenv("HDT_GUARDIAN_DENIED_CODE", "denied_by_policy")
    event_purpose = os.getenv("HDT_GUARDIAN_EVENT_PURPOSE", "coaching")

    print(f"[guardian] Repo root: {_REPO_ROOT}")
    print(f"[guardian] Gateway module: {gateway_module}")
    print(f"[guardian] MCP_CLIENT_ID={os.getenv('MCP_CLIENT_ID')} (should be GUARDIAN_AGENT)")
    print(f"[guardian] Watching client_id={watch_client}")
    print(f"[guardian] lookback_s={lookback_s}, min_denies={min_denies}")
    print(f"[guardian] pattern: ok=false, error_code={denied_code}, event_purpose={event_purpose}")

    server = StdioServerParameters(
        command=python_cmd,
        args=["-m", gateway_module],
        env=dict(os.environ, MCP_TRANSPORT="stdio"),
    )

    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # Query telemetry (purpose=analytics to pass lane validation; filter by event_purpose).
            res = await session.call_tool(
                "hdt.telemetry.query.v1",
                {
                    "n": 200,
                    "lookback_s": lookback_s,
                    "client_id": watch_client,
                    "event_purpose": event_purpose,
                    "ok": False,
                    "error_code": denied_code,
                    "purpose": "analytics",
                },
            )
            out = _coerce_json(_unwrap_tool_result(res))

    if not isinstance(out, dict) or "records" not in out:
        print("[guardian] Unexpected telemetry response:")
        print(_pretty(out))
        return 0

    records: List[Dict[str, Any]] = out.get("records") or []

    # Count denied tool calls per tool
    counts: Dict[str, int] = {}
    evidence: Dict[str, List[Tuple[str, str]]] = {}

    for r in records:
        tool_name = r.get("name") or "(unknown)"
        counts[tool_name] = counts.get(tool_name, 0) + 1

        # keep small evidence (ts,corr_id)
        evidence.setdefault(tool_name, []).append((str(r.get("ts")), str(r.get("corr_id"))))

    suspicious_tools = {t: c for t, c in counts.items() if c >= min_denies}

    if not suspicious_tools:
        print(f"[guardian] OK: no tool exceeded min_denies={min_denies} in the last {lookback_s}s.")
        print(f"[guardian] denies observed: {counts or '{}'}")
        return 0

    print("[guardian] SUSPICIOUS: repeated denied attempts detected")
    print(_pretty(suspicious_tools))

    for tool_name, c in sorted(suspicious_tools.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"\n[guardian] evidence for {tool_name} (showing up to 5):")
        for ts, cid in evidence.get(tool_name, [])[-5:]:
            print(f"  - ts={ts} corr_id={cid}")

    # Non-zero to make it usable in CI/automation
    return 3


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
