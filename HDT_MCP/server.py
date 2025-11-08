from typing import Literal, TypedDict
import os
import json
import requests
from mcp.server.fastmcp import FastMCP
import time as _time
import datetime as _dt
from pathlib import Path
from dotenv import load_dotenv


# Load .env from repo root (…/HDT-agentic-interop/.env)
ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(ENV_PATH)  # replaces your plain load_dotenv()

# Your existing API that the MCP façade talks to (your Flask/whatever service).
HDT_API_BASE = os.environ.get("HDT_API_BASE", "http://localhost:5000")
# If your API uses a key/header, grab it from env. Adjust header name if needed.
HDT_API_KEY  = os.environ.get("HDT_API_KEY", os.environ.get("MODEL_DEVELOPER_1_API_KEY", ""))  # reuse your .env
print(f"[HDT-MCP] HDT_API_BASE={HDT_API_BASE}  HDT_API_KEY={'<set>' if HDT_API_KEY else '<missing>'}")

_ENABLE_POLICY = (os.getenv("HDT_ENABLE_POLICY_TOOLS", "0") or "").strip().lower() in {"1","true","yes","on"}
print(f"[HDT-MCP] POLICY_TOOLS={_ENABLE_POLICY} (HDT_ENABLE_POLICY_TOOLS={os.getenv('HDT_ENABLE_POLICY_TOOLS')})")

_TELEMETRY_DIR = Path(__file__).parent / "telemetry"
_TELEMETRY_DIR.mkdir(exist_ok=True)

_cache: dict[tuple[str, tuple], tuple[float, dict]] = {}
_CACHE_TTL = 15.0  # seconds

# Create the MCP server façade (B0: MCP Core / Orchestrator)
mcp = FastMCP(
    name="HDT-MCP",
    instructions="Façade exposing HDT data & decisions as MCP tools/resources.",
    website_url="https://github.com/oaglazunova/Interoperable-and-modular-HDT-system-prototype",
)


# --- helpers ----------------------------------------------------------------

def _headers() -> dict[str, str]:
    """Send the key in both header styles (your Flask accepts either)."""
    if not HDT_API_KEY:
        return {}
    return {
        "X-API-KEY": HDT_API_KEY,
        "Authorization": f"Bearer {HDT_API_KEY}",
    }

def _api_url(path: str) -> str:
    """Robust join of base + path (no double/missing slashes)."""
    return f"{HDT_API_BASE.rstrip('/')}/{path.lstrip('/')}"

def _hdt_get(path: str, params: dict | None=None) -> dict:
    url = _api_url(path)
    r = requests.get(url, headers=_headers(), params=params or {}, timeout=60)
    r.raise_for_status()
    return r.json()

def _log_event(kind: str, name: str, args: dict, ok: bool, ms: int) -> None:
    rec = {
        "ts": _dt.datetime.utcnow().isoformat() + "Z",
        "kind": kind,  # "tool" | "resource"
        "name": name,
        "args": args,
        "ok": ok,
        "ms": ms,
    }
    with open(_TELEMETRY_DIR / "mcp-telemetry.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")

def _cached_get(path: str, params: dict | None=None) -> dict:
    key = (path, tuple(sorted((params or {}).items())))
    now = _time.time()
    hit = _cache.get(key)
    if hit and now - hit[0] < _CACHE_TTL:
        return hit[1]
    data = _hdt_get(path, params)
    _cache[key] = (now, data)
    return data


# ---------- RESOURCES (context / “read-only”) ----------
# Resources are things the agent can "open" for context, like files/URIs.

@mcp.resource("vault://user/{user_id}/integrated")
def get_integrated_view(user_id: str) -> dict:
    """
    Minimal integrated view: pulls walk data from the API and returns
    raw records + tiny rollups. Extend with trivia/sugarvita later.
    """
    # walk
    walk = tool_get_walk_data(user_id)  # reuse our tool
    records = []
    if isinstance(walk, list):
        # API may already return a list of user envelopes
        # normalize to just this user's records
        leaf = next((r for r in walk if str(r.get("user_id")) == str(user_id)), None)
        records = (leaf or {}).get("data", []) or (leaf or {}).get("records", [])
    elif isinstance(walk, dict):
        # façade might already return {'records': [...]}
        records = walk.get("records", walk.get("data", [])) or []

    # primitive rollups
    days = len(records)
    total_steps = sum(int(r.get("steps", 0) or 0) for r in records)
    avg_steps = int(total_steps / days) if days else 0

    return {
        "user_id": user_id,
        "streams": {
            "walk": {
                "records": records,
                "stats": {"days": days, "total_steps": total_steps, "avg_steps": avg_steps}
            }
        },
        "generated_at": int(_time.time())
    }


@mcp.resource("hdt://{user_id}/sources")
def list_sources(user_id: str) -> dict:
    """Expose connected sources for a user (which adapters are active) (DH).
    (what the README calls out in config/users.json)."""
    try:
        with open("config/users.json", "r", encoding="utf-8") as f:
            root = json.load(f)
        users = root.get("users", [])
        u = next((u for u in users if str(u.get("user_id")) == str(user_id)), None)
    except FileNotFoundError:
        u = None
    return {"user_id": user_id, "sources": (u or {}).get("connected_apps_walk_data", [])}

@mcp.resource("registry://tools")
def registry_tools() -> dict:
    return {
        "server": "HDT-MCP",
        "tools": [
            {"name": "hdt.get_walk_data@v1", "args": ["user_id"]},
            {"name": "hdt.get_trivia_data@v1", "args": ["user_id"]},
            {"name": "hdt.get_sugarvita_data@v1", "args": ["user_id"]},
        ]
    }


# --- 2) TOOLS (actions / compute) -------------------------------------------
# Tools are callables with typed params; MCP auto-generates JSON Schemas (B1).

@mcp.tool(name="hdt.get_trivia_data@v1")
def tool_get_trivia_data(user_id: str) -> dict:
    """Wraps /get_trivia_data endpoint."""
    t0 = _time.time()
    try:
        out = _cached_get("/get_trivia_data", {"user_id": user_id})
        _log_event("tool", "hdt.get_trivia_data@v1", {"user_id": user_id}, True, int((_time.time()-t0)*1000))
        return out
    except Exception as e:
        _log_event("tool", "hdt.get_trivia_data@v1", {"user_id": user_id, "error": str(e)}, False, int((_time.time()-t0)*1000))
        return {"error": str(e), "user_id": user_id}

@mcp.tool(name="hdt.get_sugarvita_data@v1")
def tool_get_sugarvita_data(user_id: str) -> dict:
    """Wraps /get_sugarvita_data endpoint."""
    t0 = _time.time()
    try:
        out = _cached_get("/get_sugarvita_data", {"user_id": user_id})
        _log_event("tool", "hdt.get_sugarvita_data@v1", {"user_id": user_id}, True, int((_time.time()-t0)*1000))
        return out
    except Exception as e:
        _log_event("tool", "hdt.get_sugarvita_data@v1", {"user_id": user_id, "error": str(e)}, False, int((_time.time()-t0)*1000))
        return {"error": str(e), "user_id": user_id}

@mcp.tool(name="hdt.get_walk_data@v1")
def tool_get_walk_data(user_id: str) -> dict:
    """Wraps /get_walk_data endpoint."""
    t0 = _time.time()
    try:
        out = _cached_get("/get_walk_data", {"user_id": user_id})
        _log_event("tool", "hdt.get_walk_data@v1", {"user_id": user_id}, True, int((_time.time()-t0)*1000))
        return out
    except Exception as e:
        _log_event("tool", "hdt.get_walk_data@v1", {"user_id": user_id, "error": str(e)}, False, int((_time.time()-t0)*1000))
        return {"error": str(e), "user_id": user_id}

@mcp.tool(name="policy.evaluate@v1")
def policy_evaluate(purpose: Literal["analytics", "modeling", "coaching"] = "analytics") -> dict:
    enabled = (os.getenv("HDT_ENABLE_POLICY_TOOLS", "1").strip().lower() in {"1","true","yes","on"})
    if not enabled:
        return {
            "purpose": purpose,
            "allow": False,
            "redact_fields": [],
            "disabled": True,
            "reason": "HDT_ENABLE_POLICY_TOOLS=0"
        }
    return {"purpose": purpose, "allow": True, "redact_fields": []}


# --- 3) “Model Hub” placeholders (M1/M2) ------------------------------------
# Kept lightweight (no LLM). You can replace these with real models later.

class Strategy(TypedDict):
    stage: Literal[
        "precontemplation",
        "contemplation",
        "preparation",
        "action",
        "maintenance",
    ]
    com_b_focus: list[Literal["Capability", "Opportunity", "Motivation"]]
    suggestions: list[str]
    bct_refs: list[str]


class TimingPlan(TypedDict):
    next_window_local: str
    rationale: str

@mcp.tool(name="intervention_time@v1")
def intervention_time(local_tz: str = "Europe/Amsterdam",
                      preferred_hours: tuple[int, int] = (18, 21),
                      min_gap_hours: int = 6,
                      last_prompt_iso: str | None = None) -> TimingPlan:
    """
    Simple heuristic that returns an evening window; replace with analytics later.
    """
    # (You could also read recent activity from your adapters and tailor this.)
    start, end = preferred_hours
    return {
        "next_window_local": f"today {start:02d}:00–{end:02d}:00 {local_tz}",
        "rationale": f"Respect ≥{min_gap_hours}h gap; evening adherence tendency."
    }

# --- 4) Entrypoint / Transport ---------------------------------------------

def main():
    """
    Run the MCP server using either stdio (great for local dev) or streamable-http
    (handy for desktop agents / remote clients). Choose via MCP_TRANSPORT env var.
    """
    transport = os.environ.get("MCP_TRANSPORT", "stdio")  # "stdio" or "streamable-http"
    mcp.run(transport=transport)

if __name__ == "__main__":
    main()
