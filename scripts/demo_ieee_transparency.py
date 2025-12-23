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


def _pretty(obj) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False)


def _benign_stdio_shutdown_error(exc: BaseException) -> bool:
    # anyio/mcp shutdown edge-case (seen with mcp==1.25.x)
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


def _tail_jsonl(path: Path, n: int = 50) -> list[dict]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()[-max(50, n):]
    out: list[dict] = []
    for ln in lines[-n:]:
        try:
            out.append(json.loads(ln))
        except Exception:
            continue
    return out


def _filter_by_corr(records: list[dict], corr_id: str) -> list[dict]:
    return [r for r in records if str(r.get("corr_id")) == corr_id]


async def main() -> None:
    root = repo_root()
    policy_path = (root / "config" / "policy_ieee_demo.json").resolve()
    if not policy_path.exists():
        raise SystemExit(f"Policy file not found: {policy_path}.\n"                         f"Tip: run from repo root or set HDT_REPO_ROOT / HDT_POLICY_PATH.")

    # Use a new per-run directory so the trace is easy to interpret.
    telemetry_dir = (root / "artifacts" / "telemetry" / f"demo_ieee_trace_{time.strftime('%Y%m%d_%H%M%S')}").resolve()
    telemetry_dir.mkdir(parents=True, exist_ok=True)

    print("\n=== IEEE Demo: Transparency / Traceability (Telemetry) ===")
    print(f"Telemetry dir: {telemetry_dir}")

    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", "hdt_mcp.gateway"],
        env=dict(
            os.environ,
            MCP_TRANSPORT="stdio",
            HDT_POLICY_PATH=str(policy_path),
            HDT_TELEMETRY_DIR=str(telemetry_dir),
            HDT_ENABLE_MOCK_SOURCES="1",
            MCP_CLIENT_ID=os.getenv("MCP_CLIENT_ID", "AUDITOR_AGENT"),
        ),
    )

    corr_id: str | None = None

    try:
        async with stdio_client(server) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Generate a short trace with one gateway tool that triggers internal Sources calls.
                print("\nCalling hdt.walk.fetch.v1 (analytics, prefer=mock)...")
                out = await _call(
                    session,
                    "hdt.walk.fetch.v1",
                    {"user_id": 1, "purpose": "analytics", "prefer": "mock", "prefer_data": "live"},
                )
                print("Result (excerpt):")
                try:
                    parsed = json.loads(out) if isinstance(out, str) else out
                except Exception:
                    parsed = out
                if isinstance(parsed, dict) and "records" in parsed:
                    parsed = {k: parsed[k] for k in parsed.keys() if k != "records"}
                print(_pretty(parsed))

                # Pull telemetry via tool (redacted) and extract corr_id.
                recent = await _call(session, "hdt.telemetry.recent.v1", {"n": 20, "purpose": "analytics"})
                recent_obj = json.loads(recent) if isinstance(recent, str) else recent
                last = (recent_obj.get("records") or [])[-1] if isinstance(recent_obj, dict) else None
                corr_id = (last or {}).get("corr_id")
                if not corr_id:
                    print("\nCould not extract corr_id from telemetry; check telemetry files directly.")
                    return

                print(f"\nCorrelation id (corr_id): {corr_id}")
                print("\nTelemetry (gateway) via hdt.telemetry.recent.v1 (already redacted):")
                print(_pretty(recent_obj))

    except BaseExceptionGroup as eg:  # Python 3.11+
        if not _benign_stdio_shutdown_error(eg):
            raise
    except RuntimeError as e:
        if not _benign_stdio_shutdown_error(e):
            raise

    # After server shuts down, read telemetry JSONL files for a compact end-to-end trace.
    gw_jsonl = telemetry_dir / "mcp-telemetry.jsonl"
    src_jsonl = telemetry_dir / "sources_mcp" / "mcp-telemetry.jsonl"

    if not corr_id:
        print("\nNo corr_id captured; nothing to filter.")
        return

    gw_recs = _filter_by_corr(_tail_jsonl(gw_jsonl, n=200), corr_id)
    src_recs = _filter_by_corr(_tail_jsonl(src_jsonl, n=200), corr_id)

    print("\n--- End-to-end trace (filtered by corr_id) ---")
    print(f"Gateway telemetry file: {gw_jsonl}")
    print(f"Sources telemetry file: {src_jsonl}")

    def _summarize(rs: list[dict]) -> list[dict]:
        out = []
        for r in rs:
            out.append(
                {
                    "ts": r.get("ts"),
                    "corr_id": r.get("corr_id"),
                    "kind": r.get("kind"),
                    "tool": r.get("tool"),
                    "ok": r.get("ok"),
                    "ms": r.get("ms"),
                    "args": r.get("args"),
                }
            )
        return out

    print("\nGateway events:")
    print(_pretty(_summarize(gw_recs)))
    print("\nSources events:")
    print(_pretty(_summarize(src_recs)))

    print("\nNotes:")
    print("- Telemetry is redacted at capture for secrets and common PII keys (user_id, email, player_id).")
    print("- corr_id is shared across gateway and sources for traceability.")


if __name__ == "__main__":
    asyncio.run(main())
