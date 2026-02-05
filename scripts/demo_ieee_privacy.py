from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from hdt_config.settings import repo_root
from hdt_mcp import vault_store

CALL_TIMEOUT_SEC = float(os.getenv('HDT_DEMO_TIMEOUT_SEC', '30'))


def _pretty(x) -> str:
    if isinstance(x, str):
        try:
            return json.dumps(json.loads(x), indent=2, ensure_ascii=False)
        except Exception:
            return x
    return json.dumps(x, indent=2, ensure_ascii=False)


def _benign_stdio_shutdown_error(exc: BaseException) -> bool:
    # anyio/mcp shutdown edge-case (seen with mcp==1.25.x):
    # "Attempted to exit cancel scope in a different task than it was entered in"
    s = str(exc)
    return "Attempted to exit" in s and "cancel scope" in s


async def _call(session: ClientSession, name: str, args: dict):
    try:
        res = await asyncio.wait_for(session.call_tool(name, args), timeout=CALL_TIMEOUT_SEC)
    except asyncio.TimeoutError:
        return {"error": {"code": "timeout", "message": f"Tool call timed out after {CALL_TIMEOUT_SEC}s", "tool": name}}
    if getattr(res, "content", None):
        c0 = res.content[0]
        return getattr(c0, "text", c0)
    return res


def _ensure_demo_vault(root: Path) -> Path:
    db_path = (root / "artifacts" / "vault" / "hdt_vault_ieee_demo.sqlite").resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    vault_store.init(str(db_path))

    # Deterministic small sample window.
    records = [
        {"date": "2025-11-01", "steps": 2310, "distance_meters": 1520.0, "duration": 900.0, "kcalories": 110.5},
        {"date": "2025-11-02", "steps": 5421, "distance_meters": 3510.0, "duration": 2100.0, "kcalories": 255.2},
        {"date": "2025-11-03", "steps": 123, "distance_meters": 80.0, "duration": 120.0, "kcalories": 7.0},
    ]
    vault_store.upsert_walk(1, records, source="gamebus")
    return db_path


async def main() -> None:
    root = repo_root()
    policy_path = (root / "config" / "policy_ieee_demo.json").resolve()
    if not policy_path.exists():
        raise SystemExit(f"Policy file not found: {policy_path}.\n"                         f"Tip: run from repo root or set HDT_REPO_ROOT / HDT_POLICY_PATH.")
    telemetry_dir = (root / "artifacts" / "telemetry" / f"demo_ieee_{time.strftime('%Y%m%d_%H%M%S')}").resolve()
    telemetry_dir.mkdir(parents=True, exist_ok=True)

    db_path = _ensure_demo_vault(root)

    print("\n=== IEEE Demo: Privacy & Purpose Lanes ===")
    print(f"Repo root: {root}")
    print(f"Policy: {policy_path}")
    print(f"Telemetry dir: {telemetry_dir}")
    print(f"Vault db: {db_path}")

    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", "hdt_mcp.gateway"],
        env=dict(
            os.environ,
            MCP_TRANSPORT="stdio",
            HDT_POLICY_PATH=str(policy_path),
            HDT_TELEMETRY_DIR=str(telemetry_dir),
            HDT_VAULT_ENABLE="1",
            HDT_VAULT_PATH=str(db_path),
            HDT_ENABLE_MOCK_SOURCES="1",
            # Demonstrate client-scoped rules. Change this and re-run to see different outcomes.
            MCP_CLIENT_ID=os.getenv("MCP_CLIENT_ID", "MODEL_DEVELOPER_1"),
        ),
    )

    try:
        async with stdio_client(server) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                print("\nTOOLS (excerpt):")
                tools = await session.list_tools()
                for t in tools.tools:
                    # if t.name.startswith("hdt.walk") or t.name.startswith("hdt.policy") or t.name.startswith("hdt.telemetry"):
                    print(f"- {t.name}")
                    # print(_pretty(t.inputSchema))

                # 1) Deny-fast: modeling on raw fetch
                print("\n1) Deny-fast: modeling + hdt.walk.fetch.v1")
                # NOTE: In the baseline v0.5.x code, the governor does not implement a "mock" live source.
                # For deterministic offline demos (and to avoid calling external systems), use the seeded vault.
                out = await _call(
                    session,
                    "hdt.walk.fetch.v1",
                    {"user_id": 1, "purpose": "modeling", "prefer": "gamebus", "prefer_data": "vault"},
                )
                print(_pretty(out))

                # 2) Allow modeling-safe output via features tool
                print("\n2) Modeling-safe: modeling + hdt.walk.features.v1")
                out = await _call(
                    session,
                    "hdt.walk.features.v1",
                    {"user_id": 1, "purpose": "modeling", "prefer": "gamebus", "prefer_data": "vault"},
                )
                print(_pretty(out))

                # 3) Coaching: more sensitive view; policy redacts provenance.email
                print("\n3) Coaching lane: coaching + hdt.walk.fetch.v1 (vault-only)")
                out = await _call(
                    session,
                    "hdt.walk.fetch.v1",
                    {"user_id": 1, "purpose": "coaching", "prefer": "gamebus", "prefer_data": "vault"},
                )
                print(_pretty(out))

                # 4) Analytics: minimized view; policy redacts kcalories across records
                print("\n4) Analytics lane: analytics + hdt.walk.fetch.v1 (vault-only)")
                out = await _call(
                    session,
                    "hdt.walk.fetch.v1",
                    {"user_id": 1, "purpose": "analytics", "prefer": "gamebus", "prefer_data": "vault"},
                )
                print(_pretty(out))

                # 5) Vault-only: deterministic offline (no external sources)
                print("\n5) Vault-only: analytics + hdt.walk.fetch.v1 (prefer_data=vault)")
                out = await _call(session, "hdt.walk.fetch.v1", {"user_id": 1, "purpose": "analytics", "prefer": "gamebus", "prefer_data": "vault"})
                print(_pretty(out))

                # 6) Explain policy for one call
                print("\n6) Policy explain: hdt.walk.fetch.v1 (analytics)")
                out = await _call(session, "hdt.policy.explain.v1", {"tool": "hdt.walk.fetch.v1", "purpose": "analytics"})
                print(_pretty(out))

                print("\nNext step: run scripts/demo_ieee_transparency.py to see the trace (gateway/governor; sources when enabled).")
    except BaseExceptionGroup as eg:  # Python 3.11+
        if not _benign_stdio_shutdown_error(eg):
            raise
    except RuntimeError as e:
        if not _benign_stdio_shutdown_error(e):
            raise


if __name__ == "__main__":
    asyncio.run(main())
