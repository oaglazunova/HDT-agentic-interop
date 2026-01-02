from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from datetime import datetime

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from hdt_config.settings import repo_root

CALL_TIMEOUT_SEC = float(os.getenv("HDT_DEMO_TIMEOUT_SEC", "30"))


def _pretty(x) -> str:
    if isinstance(x, str):
        try:
            x = json.loads(x)
        except Exception:
            return x
    return json.dumps(x, indent=2, ensure_ascii=False)


async def _call(session: ClientSession, tool: str, args: dict):
    # Ensure the demo cannot hang indefinitely
    res = await asyncio.wait_for(session.call_tool(tool, args), timeout=CALL_TIMEOUT_SEC)
    if getattr(res, "content", None):
        c0 = res.content[0]
        return getattr(c0, "text", c0)
    return res


def _tail_jsonl(path: Path, n: int = 200) -> list[dict]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    out: list[dict] = []
    for ln in lines[-n:]:
        try:
            out.append(json.loads(ln))
        except Exception:
            continue
    return out


def _summarize(records: list[dict], corr_id: str | None) -> dict:
    if corr_id:
        records = [r for r in records if r.get("corr_id") == corr_id]

    def _get_tool(r: dict) -> str | None:
        # New schema: "name" (tool name). Back-compat: "tool".
        return r.get("name") or r.get("tool")

    def _get_purpose(r: dict) -> str | None:
        # New schema usually stores purpose under args.purpose
        if r.get("purpose") is not None:
            return r.get("purpose")

        a = r.get("args") or {}
        if isinstance(a, dict):
            if a.get("purpose") is not None:
                return a.get("purpose")
            # Some payloads may nest under args.args
            inner = a.get("args")
            if isinstance(inner, dict) and inner.get("purpose") is not None:
                return inner.get("purpose")
        return None

    def _get_policy(r: dict):
        # New schema: args.policy
        if r.get("policy") is not None:
            return r.get("policy")
        a = r.get("args") or {}
        if isinstance(a, dict):
            return a.get("policy")
        return None

    def _get_status(r: dict) -> str | None:
        # New schema: ok boolean. Back-compat: status string.
        if r.get("status") is not None:
            return r.get("status")
        if r.get("ok") is True:
            return "ok"
        if r.get("ok") is False:
            return "error"
        return None

    def one(r: dict) -> dict:
        return {
            "ts": r.get("ts"),
            "corr_id": r.get("corr_id"),
            "client_id": r.get("client_id"),
            "tool": _get_tool(r),
            "purpose": _get_purpose(r),
            "status": _get_status(r),
            "policy": _get_policy(r),
            "ms": r.get("ms"),
            "request_id": r.get("request_id"),
        }

    return {"n": len(records), "records": [one(r) for r in records[-12:]]}


def _ensure_seeded_vault(root: Path, vault_db: Path) -> None:
    if vault_db.exists():
        return
    # Seed vault deterministically (offline demo)
    script = root / "scripts" / "init_sample_vault.py"
    if not script.exists():
        raise RuntimeError(f"Missing vault seeding script: {script}")

    env = dict(os.environ)
    env["HDT_VAULT_ENABLE"] = "1"
    env["HDT_VAULT_PATH"] = str(vault_db)

    subprocess.check_call([sys.executable, str(script)], env=env)


async def main() -> None:
    root = repo_root()

    print("\n=== IEEE Demo: Transparency / Traceability (Telemetry) ===")

    telemetry_dir = (root / "artifacts" / "telemetry" / f"demo_ieee_trace_{datetime.now():%Y%m%d_%H%M%S}").resolve()
    telemetry_dir.mkdir(parents=True, exist_ok=True)
    print(f"Telemetry dir: {telemetry_dir}")

    policy_path = (root / "config" / "policy_ieee_demo.json").resolve()
    if not policy_path.exists():
        raise SystemExit(f"Policy file not found: {policy_path}")

    vault_db = (root / "artifacts" / "vault" / "hdt_vault_ieee_demo.sqlite").resolve()
    vault_db.parent.mkdir(parents=True, exist_ok=True)
    _ensure_seeded_vault(root, vault_db)

    # Start the gateway server over stdio
    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", "hdt_mcp.gateway"],
        env=dict(
            os.environ,
            MCP_TRANSPORT="stdio",
            MCP_CLIENT_ID=os.getenv("MCP_CLIENT_ID", "AUDITOR_AGENT"),
            HDT_POLICY_PATH=str(policy_path),
            HDT_TELEMETRY_DIR=str(telemetry_dir),
            HDT_VAULT_ENABLE="1",
            HDT_VAULT_PATH=str(vault_db),
        ),
    )

    corr_id: str | None = None

    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # Generate one correlated trace using vault-only execution
            print("\nCalling hdt.walk.fetch.v1 (analytics, prefer_data=vault) ...")
            out = await _call(
                session,
                "hdt.walk.fetch.v1",
                {"user_id": 1, "purpose": "analytics", "prefer_data": "vault"},
            )
            print("Result (excerpt):")
            try:
                parsed = json.loads(out) if isinstance(out, str) else out
            except Exception:
                parsed = out
            if isinstance(parsed, dict) and "records" in parsed:
                parsed = {k: v for k, v in parsed.items() if k != "records"}
            print(_pretty(parsed))

            if isinstance(parsed, dict) and parsed.get("corr_id"):
                corr_id = parsed["corr_id"]

            # Read telemetry via tool (most robust; avoids guessing file paths)
            print("\nTelemetry via hdt.telemetry.recent.v1:")
            recent = await _call(session, "hdt.telemetry.recent.v1", {"n": 50, "purpose": "analytics"})
            recent_obj = json.loads(recent) if isinstance(recent, str) else recent
            print(_pretty(recent_obj))

            # Extract a corr_id from recent telemetry only if we didn't already get it from the tool result
            if corr_id is None and isinstance(recent_obj, dict):
                recs = recent_obj.get("records") or []
                if recs:
                    corr_id = recs[-1].get("corr_id")

    # Give Windows a moment to flush file buffers
    time.sleep(0.1)

    # Also show the JSONL telemetry files produced (for paper appendix/screenshots)
    jsonl_files = sorted(telemetry_dir.rglob("mcp-telemetry.jsonl"))
    if not jsonl_files:
        print("\nNo mcp-telemetry.jsonl files found under telemetry dir.")
        return

    print(f"\nFound {len(jsonl_files)} telemetry file(s):")
    for p in jsonl_files:
        print(f" - {p}")

    if corr_id:
        print(f"\nCorrelation id (corr_id): {corr_id}")

    for p in jsonl_files:
        recs = _tail_jsonl(p, n=300)
        print(f"\nSummary for {p.name} (filtered by corr_id if available):")
        print(_pretty(_summarize(recs, corr_id=corr_id)))


if __name__ == "__main__":
    asyncio.run(main())
