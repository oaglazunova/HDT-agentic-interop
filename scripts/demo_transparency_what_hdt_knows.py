from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

# Repo-root resolution (works even when invoked from elsewhere)
_THIS_FILE = Path(__file__).resolve()
_REPO_ROOT = _THIS_FILE.parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

LANES = ("analytics", "coaching", "modeling")

DEFAULT_START = "2025-11-01"
DEFAULT_END = "2025-11-30"


def _pretty(obj: Any) -> str:
    try:
        return json.dumps(obj, indent=2, ensure_ascii=False)
    except Exception:
        return str(obj)


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


async def _call(session: ClientSession, tool: str, args: dict, timeout_s: float) -> Any:
    try:
        res = await asyncio.wait_for(session.call_tool(tool, args), timeout=timeout_s)
    except asyncio.TimeoutError:
        return {"error": {"code": "timeout", "message": f"timeout calling {tool}"}}
    return _coerce_json(_unwrap_tool_result(res))


def _subject_hash(user_id: int) -> str | None:
    salt = os.getenv("HDT_TELEMETRY_SUBJECT_SALT", "").strip()
    if not salt:
        return None
    raw = f"{salt}:{user_id}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def _extract_records(payload: Any) -> List[dict]:
    """
    Handle both possible shapes:
      - {"records": [...]}  (raw)
      - {"streams": {"walk": {"records": [...]}}} (policy-shaped)
    """
    if not isinstance(payload, dict):
        return []
    if isinstance(payload.get("records"), list):
        return payload["records"]

    streams = payload.get("streams")
    if isinstance(streams, dict):
        for _, v in streams.items():
            if isinstance(v, dict) and isinstance(v.get("records"), list):
                return v["records"]

    return []


def _inventory_summary(domain: str, payload: Any) -> dict:
    if not isinstance(payload, dict):
        return {"domain": domain, "status": "unknown", "note": "non-dict payload"}

    if "error" in payload:
        return {
            "domain": domain,
            "status": "error",
            "error": payload.get("error"),
            "selected_source": payload.get("selected_source"),
        }

    recs = _extract_records(payload)
    if not recs:
        return {
            "domain": domain,
            "status": "ok",
            "records": 0,
            "selected_source": payload.get("selected_source"),
            "note": "no records returned (may still be configured but empty / filtered)",
        }

    # best-effort date range
    dates = [r.get("date") for r in recs if isinstance(r, dict) and r.get("date")]
    dates = [d for d in dates if isinstance(d, str)]
    dates.sort()

    fields = sorted({k for r in recs if isinstance(r, dict) for k in r.keys()})

    return {
        "domain": domain,
        "status": "ok",
        "records": len(recs),
        "date_range": {"min": dates[0], "max": dates[-1]} if dates else None,
        "fields": fields[:12],
        "selected_source": payload.get("selected_source"),
    }


def _summarize_access(records: List[dict]) -> dict:
    """
    Summarize tool usage by tool → purpose → client_id.
    """
    buckets: Dict[Tuple[str, str, str], dict] = {}
    for r in records:
        if not isinstance(r, dict):
            continue

        name = r.get("name")
        if not isinstance(name, str) or not name.startswith("hdt."):
            continue

        # ignore telemetry introspection tools to keep output user-facing
        if name in {"hdt.telemetry.recent.v1", "hdt.telemetry.query.v1"}:
            continue

        client_id = r.get("client_id") or "UNKNOWN_CLIENT"
        purpose = None

        # In your instrumentation, purpose is stored in r["args"]["purpose"].
        args = r.get("args") or {}
        if isinstance(args, dict):
            purpose = args.get("purpose")

        purpose = str(purpose) if purpose else "unknown"
        ok = bool(r.get("ok"))

        err_code = None
        if isinstance(args, dict) and isinstance(args.get("error"), dict):
            err_code = args["error"].get("code")

        key = (name, purpose, str(client_id))
        b = buckets.setdefault(
            key,
            {
                "tool": name,
                "purpose": purpose,
                "client_id": str(client_id),
                "calls": 0,
                "ok": 0,
                "error": 0,
                "errors": {},
                "last_ts": None,
            },
        )

        b["calls"] += 1
        if ok:
            b["ok"] += 1
        else:
            b["error"] += 1
            if err_code:
                b["errors"][err_code] = b["errors"].get(err_code, 0) + 1

        ts = r.get("ts")
        if isinstance(ts, str):
            b["last_ts"] = ts if (b["last_ts"] is None or ts > b["last_ts"]) else b["last_ts"]

    out = list(buckets.values())
    out.sort(key=lambda x: (x["tool"], x["purpose"], x["client_id"]))
    return {"groups": out, "groups_n": len(out)}


async def main() -> int:
    timeout_s = float(os.getenv("HDT_DEMO_TIMEOUT_SEC", "30"))

    user_id = int(os.getenv("HDT_SMOKE_USER_ID", "1"))
    gateway_module = os.getenv("HDT_GATEWAY_MODULE", "hdt_mcp.gateway")
    python_cmd = os.getenv("MCP_PYTHON") or sys.executable

    # Deterministic defaults (honor env if set)
    policy_path = os.getenv("HDT_POLICY_PATH") or str(_REPO_ROOT / "config" / "policy_ieee_demo.json")
    vault_path = os.getenv("HDT_VAULT_PATH") or str(_REPO_ROOT / "artifacts" / "vault" / "hdt_vault_ieee_demo.sqlite")

    # Ensure seeded vault for offline demo
    vault_db = Path(vault_path)
    vault_db.parent.mkdir(parents=True, exist_ok=True)
    if not vault_db.exists():
        subprocess.check_call([sys.executable, str(_REPO_ROOT / "scripts" / "init_sample_vault.py")], env=dict(os.environ))

    telemetry_dir = (_REPO_ROOT / "artifacts" / "telemetry" / f"demo_what_hdt_knows_{datetime.now():%Y%m%d_%H%M%S}").resolve()
    telemetry_dir.mkdir(parents=True, exist_ok=True)

    server_env = dict(os.environ)
    server_env.setdefault("MCP_CLIENT_ID", os.getenv("MCP_CLIENT_ID", "WHAT_HDT_KNOWS_AGENT"))
    server_env["MCP_TRANSPORT"] = "stdio"
    server_env.setdefault("HDT_POLICY_PATH", policy_path)
    server_env.setdefault("HDT_VAULT_ENABLE", "1")
    server_env.setdefault("HDT_VAULT_PATH", str(vault_db))
    server_env.setdefault("HDT_TELEMETRY_DIR", str(telemetry_dir))

    server = StdioServerParameters(
        command=python_cmd,
        args=["-m", gateway_module],
        env=server_env,
    )

    print("\n=== \"What does the HDT know about me?\" (Transparency Agent) ===")
    print(f"User: user_id={user_id}")
    print(f"Policy: {server_env.get('HDT_POLICY_PATH')}")
    print(f"Telemetry dir: {telemetry_dir}")
    print(f"MCP_CLIENT_ID (server attribution): {server_env.get('MCP_CLIENT_ID')}")

    subject_hash = _subject_hash(user_id)
    if subject_hash:
        print(f"subject_hash (telemetry linkability): {subject_hash}")

    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # 1) Policy snapshot for key tools
            tools_of_interest = [
                "hdt.sources.status.v1",
                "hdt.walk.fetch.v1",
                "hdt.walk.features.v1",
                "hdt.trivia.fetch.v1",
                "hdt.sugarvita.fetch.v1",
            ]

            policy_matrix: Dict[str, Dict[str, Any]] = {}
            for t in tools_of_interest:
                policy_matrix[t] = {}
                for lane in LANES:
                    out = await _call(session, "hdt.policy.explain.v1", {"tool": t, "purpose": lane}, timeout_s)
                    if isinstance(out, dict) and "error" not in out:
                        policy_matrix[t][lane] = {"allow": out.get("allow"), "redact": out.get("redact", [])}
                    else:
                        policy_matrix[t][lane] = {"allow": None, "error": out.get("error") if isinstance(out, dict) else out}

            # 2) Data inventory (bounded)
            sources = await _call(session, "hdt.sources.status.v1", {"user_id": user_id, "purpose": "analytics"}, timeout_s)

            walk = await _call(
                session,
                "hdt.walk.fetch.v1",
                {
                    "user_id": user_id,
                    "start_date": DEFAULT_START,
                    "end_date": DEFAULT_END,
                    "prefer_data": "vault",
                    "limit": 5,
                    "purpose": "analytics",
                },
                timeout_s,
            )

            feats = await _call(
                session,
                "hdt.walk.features.v1",
                {
                    "user_id": user_id,
                    "start_date": DEFAULT_START,
                    "end_date": DEFAULT_END,
                    "prefer_data": "vault",
                    "purpose": "modeling",
                },
                timeout_s,
            )

            trivia = await _call(
                session,
                "hdt.trivia.fetch.v1",
                {"user_id": user_id, "start_date": DEFAULT_START, "end_date": DEFAULT_END, "purpose": "analytics"},
                timeout_s,
            )

            sugarvita = await _call(
                session,
                "hdt.sugarvita.fetch.v1",
                {"user_id": user_id, "start_date": DEFAULT_START, "end_date": DEFAULT_END, "purpose": "analytics"},
                timeout_s,
            )

            inventory = {
                "sources": sources if isinstance(sources, dict) else {"note": "non-dict"},
                "walk": _inventory_summary("walk", walk),
                "walk_features": {
                    "domain": "walk_features",
                    "status": "error" if isinstance(feats, dict) and "error" in feats else "ok",
                    "selected_source": feats.get("selected_source") if isinstance(feats, dict) else None,
                    "feature_keys": sorted(list((feats.get("features") or {}).keys()))[:20]
                    if isinstance(feats, dict) and isinstance(feats.get("features"), dict)
                    else None,
                    "error": feats.get("error") if isinstance(feats, dict) else None,
                },
                "trivia": _inventory_summary("trivia", trivia),
                "sugarvita": _inventory_summary("sugarvita", sugarvita),
            }

            # 3) Access transparency via telemetry query tool
            query_args = {"n": 200, "lookback_s": 86400 * 30, "tool_prefix": "hdt.", "purpose": "analytics"}
            if subject_hash:
                query_args["subject_hash"] = subject_hash

            telemetry = await _call(session, "hdt.telemetry.query.v1", query_args, timeout_s)

            # fallback if query tool not available for some reason
            if isinstance(telemetry, dict) and isinstance(telemetry.get("error"), dict):
                telemetry = await _call(session, "hdt.telemetry.recent.v1", {"n": 200, "purpose": "analytics"}, timeout_s)

            records = []
            if isinstance(telemetry, dict) and isinstance(telemetry.get("records"), list):
                records = telemetry["records"]

            access_summary = _summarize_access(records)

    # Print human-readable output
    print("\n--- Data inventory (bounded) ---")
    print(_pretty(inventory))

    print("\n--- Policy snapshot (tool × lane) ---")
    print(_pretty(policy_matrix))

    print("\n--- Access transparency (telemetry summary) ---")
    print(_pretty(access_summary))

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
