from __future__ import annotations

"""IEEE demo: policy matrix (clients x purposes x tools).

This script is meant for artifact evaluation / peer review:

* It starts the HDT MCP gateway in stdio mode for multiple `MCP_CLIENT_ID` values.
* It queries `hdt.policy.explain.v1` to show the *resolved* rule (allow + redactions).
* It executes a small set of representative tool calls to demonstrate deny-fast behavior.

The output is printed to stdout and can optionally be exported as JSON.

Usage:
  python scripts/demo_ieee_policy_matrix.py
  python scripts/demo_ieee_policy_matrix.py --out artifacts/ieee_demo/policy_matrix.json
"""

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from hdt_config.settings import repo_root


def _pretty(obj) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False)


async def _call(session: ClientSession, name: str, args: dict):
    try:
        res = await asyncio.wait_for(session.call_tool(name, args), timeout=CALL_TIMEOUT_SEC)
    except asyncio.TimeoutError:
        return {"error": {"code": "timeout", "message": f"Tool call timed out after {CALL_TIMEOUT_SEC}s", "tool": name}}
    if getattr(res, "content", None):
        c0 = res.content[0]
        return getattr(c0, "text", c0)
    return res


def _benign_stdio_shutdown_error(exc: BaseException) -> bool:
    s = str(exc)
    return "Attempted to exit" in s and "cancel scope" in s


async def _run_for_client(*, client_id: str, policy_path: Path, telemetry_dir: Path) -> dict:
    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", "hdt_mcp.gateway"],
        env=dict(
            os.environ,
            MCP_TRANSPORT="stdio",
            MCP_CLIENT_ID=client_id,
            HDT_POLICY_PATH=str(policy_path),
            HDT_TELEMETRY_DIR=str(telemetry_dir / client_id),
            HDT_ENABLE_MOCK_SOURCES="1",
        ),
    )

    tools = [
        "hdt.walk.fetch.v1",
        "hdt.walk.features.v1",
        "hdt.policy.explain.v1",
    ]
    purposes = ["analytics", "coaching", "modeling"]

    out: dict = {"client_id": client_id, "policy": [], "calls": []}

    try:
        async with stdio_client(server) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # 1) policy explain matrix
                for tool in tools:
                    for purpose in purposes:
                        exp = await _call(session, "hdt.policy.explain.v1", {"tool": tool, "purpose": purpose})
                        exp_obj = json.loads(exp) if isinstance(exp, str) else exp
                        out["policy"].append(exp_obj)

                # 2) representative tool calls
                # - modeling on raw fetch should be denied before governor/sources
                r1 = await _call(session, "hdt.walk.fetch.v1", {"user_id": 1, "purpose": "modeling", "prefer": "mock", "prefer_data": "live"})
                # - analytics raw fetch should succeed (and be redacted)
                r2 = await _call(session, "hdt.walk.fetch.v1", {"user_id": 1, "purpose": "analytics", "prefer": "mock", "prefer_data": "live"})
                # - modeling features should succeed
                r3 = await _call(session, "hdt.walk.features.v1", {"user_id": 1, "purpose": "modeling", "prefer": "mock", "prefer_data": "live"})

                def _parse(x):
                    try:
                        return json.loads(x) if isinstance(x, str) else x
                    except Exception:
                        return x

                out["calls"].append({"tool": "hdt.walk.fetch.v1", "purpose": "modeling", "result": _parse(r1)})
                out["calls"].append({"tool": "hdt.walk.fetch.v1", "purpose": "analytics", "result": _parse(r2)})
                out["calls"].append({"tool": "hdt.walk.features.v1", "purpose": "modeling", "result": _parse(r3)})

    except BaseExceptionGroup as eg:  # Python 3.11+
        if not _benign_stdio_shutdown_error(eg):
            raise
    except RuntimeError as e:
        if not _benign_stdio_shutdown_error(e):
            raise

    return out


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=str, default="", help="Write JSON output to this path")
    args = ap.parse_args()

    root = repo_root()
    policy_path = (root / "config" / "policy_ieee_demo.json").resolve()
    if not policy_path.exists():
        raise SystemExit(f"Policy file not found: {policy_path}.\n"                         f"Tip: run from repo root or set HDT_REPO_ROOT / HDT_POLICY_PATH.")
    telemetry_dir = (root / "artifacts" / "telemetry" / f"demo_ieee_policy_{time.strftime('%Y%m%d_%H%M%S')}").resolve()
    telemetry_dir.mkdir(parents=True, exist_ok=True)

    print("\n=== IEEE Demo: Policy Matrix (clients x purposes x tools) ===")
    print(f"Policy: {policy_path}")
    print(f"Telemetry dir: {telemetry_dir}")

    clients = ["MODEL_DEVELOPER_1", "AUDITOR_AGENT", "COACH_APP"]
    results = []
    for cid in clients:
        print(f"\n--- Client: {cid} ---")
        r = await _run_for_client(client_id=cid, policy_path=policy_path, telemetry_dir=telemetry_dir)
        results.append(r)

        # Print a compact human-readable summary.
        for call in r["calls"]:
            tool = call["tool"]
            purpose = call["purpose"]
            res = call["result"]
            ok = isinstance(res, dict) and ("error" not in res)
            print(f"{tool} [{purpose}]: {'OK' if ok else 'DENIED/ERROR'}")

    if args.out:
        out_path = Path(args.out).expanduser().resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(_pretty({"results": results}), encoding="utf-8")
        print(f"\nWrote: {out_path}")

    # Print the full JSON last so it can be captured by tooling.
    print("\nFull JSON (for capture):")
    print(_pretty({"results": results}))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
