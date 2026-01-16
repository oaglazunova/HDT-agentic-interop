"""
Smoke script for MCP reachability + policy demo (no REST).

It performs:
 1) MCP Gateway health check via stdio (spawns the gateway module)
 2) Lists tools and calls hdt.healthz.v1
 3) Calls hdt.sources.status.v1 (optional but recommended)
 4) Policy demonstration: loads policy from HDT_POLICY_PATH (or config/policy.json)
    and applies it to a sample payload, showing redactions.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

# Ensure repo root is on sys.path BEFORE importing repo packages
_THIS_FILE = Path(__file__).resolve()
_REPO_ROOT = _THIS_FILE.parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from hdt_mcp.policy import engine as pol  # noqa: E402


def _pretty(x: Any) -> str:
    if isinstance(x, str):
        s = x.strip()
        if s.startswith("{") or s.startswith("["):
            try:
                return json.dumps(json.loads(s), indent=2, ensure_ascii=False)
            except Exception:
                return x
        return x
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


async def demo_mcp() -> bool:
    # Lazy import so the script remains usable even outside pre-commit envs
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client, StdioServerParameters

    gateway_module = os.getenv("HDT_GATEWAY_MODULE", "hdt_mcp.gateway")

    python_cmd = os.getenv("MCP_PYTHON") or sys.executable
    user_id = int(os.getenv("HDT_SMOKE_USER_ID", "1"))
    purpose = os.getenv("HDT_SMOKE_PURPOSE", "analytics")

    # In CI, stdout can be fully buffered; force flushing for progressive logs.
    print(f"[smoke] Repo root: {_REPO_ROOT}", flush=True)
    print(f"[smoke] Gateway module: {gateway_module}", flush=True)
    print(f"[smoke] Python: {python_cmd}", flush=True)
    print(f"[smoke] user_id={user_id}, purpose={purpose}", flush=True)

    # Defensive timeouts: if the underlying transport stalls, we fail fast
    # instead of waiting for the GitHub Actions step timeout.
    call_timeout_s = float(os.getenv("HDT_SMOKE_CALL_TIMEOUT_S", "30"))

    async def _list_tools(session: ClientSession):
        return await asyncio.wait_for(session.list_tools(), timeout=call_timeout_s)

    async def _call(session: ClientSession, name: str, args: dict):
        return await asyncio.wait_for(session.call_tool(name, args), timeout=call_timeout_s)

    server = StdioServerParameters(
        command=python_cmd,
        args=["-m", gateway_module],
        env=dict(os.environ, MCP_TRANSPORT="stdio"),
    )

    ok = True

    def _benign_stdio_shutdown_error(exc: BaseException) -> bool:
        s = str(exc)
        return "Attempted to exit" in s and "cancel scope" in s

    try:
        async with stdio_client(server) as (read, write):
            async with ClientSession(read, write) as session:
                await asyncio.wait_for(session.initialize(), timeout=call_timeout_s)

                tools = await _list_tools(session)
                names = [t.name for t in tools.tools]
                print("\n[smoke] TOOLS:", flush=True)
                for n in names:
                    print(f" - {n}", flush=True)

                # Gateway health check
                try:
                    res = await _call(session, "hdt.healthz.v1", {})
                    out = _unwrap_tool_result(res)
                    print("\n[smoke] CALL hdt.healthz.v1:", flush=True)
                    print(_pretty(out), flush=True)

                    if isinstance(out, str):
                        out_obj = json.loads(out) if out.strip().startswith("{") else {"text": out}
                    else:
                        out_obj = out
                    if not (isinstance(out_obj, dict) and out_obj.get("ok") is True):
                        print("[smoke] WARN: hdt.healthz.v1 did not return {'ok': True}", flush=True)
                        ok = False
                except Exception as e:
                    print(f"[smoke] ERROR: hdt.healthz.v1 failed: {e}", flush=True)
                    return False

                # Sources status (recommended)
                try:
                    res = await _call(
                        session,
                        "hdt.sources.status.v1",
                        {"user_id": user_id, "purpose": purpose},
                    )
                    out = _unwrap_tool_result(res)
                    print(f"\n[smoke] CALL hdt.sources.status.v1(user_id={user_id}):", flush=True)
                    print(_pretty(out), flush=True)
                except Exception as e:
                    print(f"[smoke] WARN: hdt.sources.status.v1 failed: {e}", flush=True)
                    ok = False

    except BaseExceptionGroup as eg:  # Python 3.11+
        if not _benign_stdio_shutdown_error(eg):
            raise
    except RuntimeError as e:
        if not _benign_stdio_shutdown_error(e):
            raise

    return ok


def demo_policy() -> bool:
    pol.policy_reset_cache()

    pol_path = os.getenv("HDT_POLICY_PATH") or str(getattr(pol, "_POLICY_PATH", ""))
    print(f"\n[smoke] Policy file: {pol_path or '(unknown)'}")

    purpose = os.getenv("HDT_SMOKE_PURPOSE", "analytics")
    tool_name = os.getenv("HDT_SMOKE_TOOL", "hdt.walk.fetch.v1")

    try:
        client_id = os.getenv("MCP_CLIENT_ID")
        rule = pol._resolve_rule(purpose, tool_name, client_id)  # demo visibility
        print(f"[smoke] Effective rule for purpose={purpose}, tool={tool_name}, client_id={client_id}:")
        print(_pretty(rule))
    except Exception as e:
        print(f"[smoke] WARN: could not resolve rule preview: {e}")

    sample = {
        "streams": {
            "walk": {
                "records": [
                    {"date": "2025-11-01", "steps": 123, "kcalories": 1.2},
                    {"date": "2025-11-02", "steps": 456, "kcalories": 9.9},
                ]
            }
        }
    }

    result, redactions = pol.apply_policy_metrics(
        purpose,
        tool_name,
        sample,
        client_id=os.getenv("MCP_CLIENT_ID"),
    )

    print(f"[smoke] redactions applied: {redactions}")
    print("[smoke] payload after policy:")
    print(_pretty(result))

    return True


async def main() -> int:
    ok_mcp = await demo_mcp()
    ok_pol = demo_policy()
    print("\n[smoke] OK" if (ok_mcp and ok_pol) else "\n[smoke] Completed with warnings")
    return 0 if (ok_mcp and ok_pol) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
