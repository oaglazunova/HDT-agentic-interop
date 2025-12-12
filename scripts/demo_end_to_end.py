# scripts/demo_end_to_end.py
from __future__ import annotations

import os
import sys
import json
import time
import textwrap
import importlib
from pathlib import Path
from typing import Any, Dict, Optional

import requests


# --- Utilities ---------------------------------------------------------------

def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]

def add_project_to_syspath() -> None:
    root = repo_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

def pp(obj: Any) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True)

def banner(title: str) -> None:
    line = "─" * max(3, 78 - len(title) - 2)
    print(f"\n== {title} {line}")

def note(msg: str) -> None:
    print(textwrap.fill(msg, width=100))


# --- API demo (ETag/304) ----------------------------------------------------

def api_demo(user_id: int = 1, limit: int = 5) -> None:
    base = os.getenv("HDT_API_BASE", "http://localhost:5000").rstrip("/")
    api_key = os.getenv("HDT_API_KEY") or os.getenv("MODEL_DEVELOPER_1_API_KEY") or "MODEL_DEVELOPER_1"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "X-API-KEY": api_key,
    }
    url = f"{base}/get_walk_data?user_id={user_id}&limit={limit}"

    banner("API demo: first GET (expect 200 + ETag)")
    try:
        r1 = requests.get(url, headers=headers, timeout=15)
    except requests.exceptions.ConnectionError:
        note("Could not reach the API. Start it first: `python -m HDT_CORE_INFRASTRUCTURE.HDT_API` "
             "or `python HDT_CORE_INFRASTRUCTURE/hdt_api.py`.")
        raise SystemExit(2)

    print(f"Status: {r1.status_code}")
    etag = r1.headers.get("ETag")
    print(f"ETag:  {etag}")
    try:
        body = r1.json()
    except Exception:
        body = {"_non_json_body": r1.text[:200]}
    # show first envelope or summary
    if isinstance(body, list) and body:
        print("First envelope (truncated):")
        preview = dict(body[0])
        if "records" in preview and isinstance(preview["records"], list) and len(preview["records"]) > 5:
            preview["records"] = preview["records"][:5] + ["…"]
        print(pp(preview))
    else:
        print(pp(body))

    banner("API demo: second GET with If-None-Match (expect 304 if unchanged)")
    if etag:
        headers_2 = dict(headers)
        headers_2["If-None-Match"] = etag
        r2 = requests.get(url, headers=headers_2, timeout=15)
        print(f"Status: {r2.status_code}")
        print("Response headers of interest:")
        for k in ("ETag", "X-Request-Id", "X-Limit", "X-Offset", "X-Total", "Link"):
            v = r2.headers.get(k)
            if v:
                print(f"  {k}: {v}")
        if r2.status_code != 304:
            note("The server returned something other than 304 (for example, data changed). "
                 "This is fine; ETag behavior depends on the exact payload & variants.")
    else:
        note("No ETag header present; skipping 304 demonstration.")


# --- MCP tool calls (in-process) --------------------------------------------

def _import_mcp_server_module() -> Any:
    """
    Import the module that defines MCP tools.
    Tries a few common names used in this repo; adjust if you renamed the file.
    """
    candidates = [
        "HDT_MCP.server",          # recommended
        "HDT_MCP.mcp_server",      # older
        "mcp_server",              # fallback
    ]
    last_err: Optional[Exception] = None
    for mod in candidates:
        try:
            return importlib.import_module(mod)
        except Exception as e:
            last_err = e
    raise RuntimeError(f"Could not import MCP server module. Tried: {candidates}. Last error: {last_err}")

def mcp_demo(user_id: int = 1) -> None:
    """
    Calls the same Python entrypoints your MCP server exposes as tools.
    This demonstrates the tool semantics even without wiring an MCP client.
    """
    banner("MCP demo: invoking tool functions directly")

    m = _import_mcp_server_module()

    # hdt.walk.stream@v1
    print("\n→ Tool: hdt.walk.stream@v1")
    stream = m.hdt_walk_stream(user_id=int(user_id), prefer="auto", start=None, end=None)
    print("source:", stream.get("source"))
    stats = stream.get("stats", {})
    print("stats:", pp({k: stats.get(k) for k in ("days", "total_steps", "avg_steps")}))
    recs = stream.get("records", [])
    if recs:
        print("first 3 records:", pp(recs[:3] + (["…"] if len(recs) > 3 else [])))

    # hdt.walk.stats@v1
    print("\n→ Tool: hdt.walk.stats@v1")
    agg = m.hdt_walk_stats(user_id=int(user_id))
    print(pp(agg))

    # behavior_strategy@v1
    print("\n→ Tool: behavior_strategy@v1")
    plan = m.tool_behavior_strategy(user_id=str(user_id))  # tool expects str
    print(pp(plan))


# --- Telemetry tail ----------------------------------------------------------

def telemetry_tail(n: int = 3) -> None:
    """
    Prints last N telemetry lines and highlights policy/redactions if present.
    """
    banner("Telemetry: last lines")

    # Try env-configured directory first, then default next to server module
    telem_dir = os.getenv("HDT_TELEMETRY_DIR")
    if telem_dir:
        p = Path(telem_dir) / "mcp-telemetry.jsonl"
    else:
        try:
            m = _import_mcp_server_module()
            p = Path(m.__file__).parent / "telemetry" / "mcp-telemetry.jsonl"
        except Exception:
            p = repo_root() / "HDT_MCP" / "telemetry" / "mcp-telemetry.jsonl"  # best-effort fallback

    if not p.exists():
        note(f"No telemetry file yet at {p}. Telemetry may be disabled or no tools were called.")
        return

    lines = p.read_text(encoding="utf-8").splitlines()[-n:]
    for i, line in enumerate(lines, 1):
        try:
            rec = json.loads(line)
        except Exception:
            print(f"{i}. [unparseable] {line[:120]}…")
            continue
        name = rec.get("name")
        ok = rec.get("ok")
        ms = rec.get("ms")
        args = rec.get("args", {}) or {}
        purpose = args.get("purpose")
        redactions = args.get("redactions")
        persisted = args.get("persisted")
        print(f"{i}. {rec.get('ts')}  {name}  ok={ok}  ms={ms}  "
              f"{('purpose='+purpose) if purpose else ''}  "
              f"{('redactions='+str(redactions)) if redactions is not None else ''}  "
              f"{('persisted='+str(persisted)) if persisted is not None else ''}".rstrip())


# --- Main --------------------------------------------------------------------

def main() -> None:
    add_project_to_syspath()

    user_id = int(os.getenv("DEMO_USER_ID", "1"))
    limit = int(os.getenv("DEMO_LIMIT", "5"))

    banner("HDT Interoperable MCP Demo")
    note("This script demonstrates: (1) API ETag/304 behavior, (2) MCP tool entrypoints, "
         "(3) telemetry with policy/redactions. Make sure the API is running.")

    api_demo(user_id=user_id, limit=limit)

    # Give filesystem a moment to flush telemetry if API and MCP share the process
    time.sleep(0.2)

    mcp_demo(user_id=user_id)

    # Another small pause to ensure log flush
    time.sleep(0.2)
    telemetry_tail(n=3)

    banner("Done")
    note("If you want to see 304 again, re-run the script immediately. To see redactions/denials, "
         "toggle config/policy.json and re-run.")

if __name__ == "__main__":
    main()
