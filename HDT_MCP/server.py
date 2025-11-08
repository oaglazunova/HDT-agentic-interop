from typing import Literal, TypedDict, Any
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

MCP_CLIENT_ID = os.getenv("MCP_CLIENT_ID", "MODEL_DEVELOPER_1")

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

_POLICY_PATH = Path(__file__).resolve().parents[1] / "config" / "policy.json"

_CACHE_TTL = int(os.getenv("HDT_CACHE_TTL", "15"))
_RETRY_MAX = int(os.getenv("HDT_RETRY_MAX", "2"))

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

def _load_policy() -> dict:
    try:
        with open(_POLICY_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"defaults": {"analytics": {"allow": True, "redact": []}}}

def _get_policy_decision(tool_name: str, purpose: str, client_id: str | None) -> dict:
    p = _load_policy()
    # precedence: tools > clients > defaults
    node = (p.get("tools", {}).get(tool_name, {}).get(purpose)
            or (p.get("clients", {}).get(client_id or "", {}).get(purpose))
            or p.get("defaults", {}).get(purpose)
            or {"allow": True, "redact": []})
    return {"allow": bool(node.get("allow", True)),
            "redact": list(node.get("redact", []))}

def _redact_inplace(obj: Any, paths: list[str]) -> Any:
    for path in paths:
        parts = path.split(".")
        _redact_path(obj, parts)
    return obj

def _redact_path(curr: Any, parts: list[str]):
    if not parts:
        return
    key = parts[0]
    rest = parts[1:]
    # lists: apply to every element
    if isinstance(curr, list):
        for item in curr:
            _redact_path(item, parts)
        return
    # dicts
    if isinstance(curr, dict):
        if not rest and key in curr:
            curr[key] = "***redacted***"
            return
        nxt = curr.get(key)
        if nxt is not None:
            _redact_path(nxt, rest)

def _with_policy(tool_name: str, payload: dict, purpose: str = "analytics") -> dict:
    decision = _get_policy_decision(tool_name, purpose, MCP_CLIENT_ID)
    out = {"allowed": decision["allow"], "purpose": purpose, "tool": tool_name}
    if not decision["allow"]:
        out["error"] = "Blocked by policy"
        return out
    # redact in a copy
    data = json.loads(json.dumps(payload))
    _redact_inplace(data, decision["redact"])
    out["data"] = data
    out["redactions_applied"] = decision["redact"]
    return out

def _hdt_get(path: str, params: dict | None=None) -> dict:
    url = _api_url(path)
    last = None
    for attempt in range(1, _RETRY_MAX + 2):
        try:
            r = requests.get(url, headers=_headers(), params=params or {}, timeout=30)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last = e
            if attempt <= _RETRY_MAX:
                _time.sleep(0.5 * attempt)  # simple backoff
            else:
                raise last


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

@mcp.resource("telemetry://recent/{n}")
def telemetry_recent(n: int = 50) -> dict:
    p = _TELEMETRY_DIR / "mcp-telemetry.jsonl"
    if not p.exists():
        return {"records": []}
    lines = p.read_text(encoding="utf-8").splitlines()[-n:]
    return {"records": [json.loads(x) for x in lines]}


# --- 2) TOOLS (actions / compute) -------------------------------------------
# Tools are callables with typed params; MCP auto-generates JSON Schemas (B1).

@mcp.tool(name="hdt.get_trivia_data@v1")
def tool_get_trivia_data(user_id: str) -> dict:
    """Wraps /get_trivia_data endpoint."""
    t0 = _time.time()
    try:
        raw = _cached_get("/get_trivia_data", {"user_id": user_id})
        wrapped = _with_policy("hdt.get_trivia_data@v1", raw)
        _log_event("tool", "hdt.get_trivia_data@v1", {"user_id": user_id}, True, int((_time.time()-t0)*1000))
        return wrapped
    except Exception as e:
        _log_event("tool", "hdt.get_trivia_data@v1", {"user_id": user_id, "error": str(e)}, False, int((_time.time()-t0)*1000))
        return {"error": str(e), "user_id": user_id}

@mcp.tool(name="hdt.get_sugarvita_data@v1")
def tool_get_sugarvita_data(user_id: str) -> dict:
    """Wraps /get_sugarvita_data endpoint."""
    t0 = _time.time()
    try:
        raw = _cached_get("/get_sugarvita_data", {"user_id": user_id})
        wrapped = _with_policy("hdt.get_sugarvita_data@v1", raw)
        _log_event("tool", "hdt.get_sugarvita_data@v1", {"user_id": user_id}, True, int((_time.time()-t0)*1000))
        return wrapped
    except Exception as e:
        _log_event("tool", "hdt.get_sugarvita_data@v1", {"user_id": user_id, "error": str(e)}, False, int((_time.time()-t0)*1000))
        return {"error": str(e), "user_id": user_id}

@mcp.tool(name="hdt.get_walk_data@v1")
def tool_get_walk_data(user_id: str, purpose: Literal["analytics","modeling","coaching"]="analytics") -> dict:
    t0 = _time.time()
    try:
        raw = _cached_get("/get_walk_data", {"user_id": user_id})
        wrapped = _with_policy("hdt.get_walk_data@v1", raw, purpose=purpose)
        _log_event("tool", "hdt.get_walk_data@v1", {"user_id": user_id, "purpose": purpose}, True, int((_time.time()-t0)*1000))
        return wrapped
    except Exception as e:
        _log_event("tool", "hdt.get_walk_data@v1", {"user_id": user_id, "purpose": purpose, "error": str(e)}, False, int((_time.time()-t0)*1000))
        return {"error": str(e), "user_id": user_id}

@mcp.tool(name="hdt.get_sugarvita_player_types@v1")
def tool_get_sugarvita_player_types(user_id: str, purpose: Literal["analytics","modeling","coaching"]="analytics") -> dict:
    t0 = _time.time()
    try:
        raw = _cached_get("/get_sugarvita_player_types", {"user_id": user_id})
        out = _with_policy("hdt.get_sugarvita_player_types@v1", raw, purpose)
        _log_event("tool", "hdt.get_sugarvita_player_types@v1", {"user_id": user_id, "purpose": purpose}, True, int((_time.time()-t0)*1000))
        return out
    except Exception as e:
        _log_event("tool", "hdt.get_sugarvita_player_types@v1", {"user_id": user_id, "purpose": purpose, "error": str(e)}, False, int((_time.time()-t0)*1000))
        return {"error": str(e), "user_id": user_id}

@mcp.tool(name="hdt.get_health_literacy_diabetes@v1")
def tool_get_health_literacy_diabetes(user_id: str, purpose: Literal["analytics","modeling","coaching"]="analytics") -> dict:
    t0 = _time.time()
    try:
        raw = _cached_get("/get_health_literacy_diabetes", {"user_id": user_id})
        out = _with_policy("hdt.get_health_literacy_diabetes@v1", raw, purpose)
        _log_event("tool", "hdt.get_health_literacy_diabetes@v1", {"user_id": user_id, "purpose": purpose}, True, int((_time.time()-t0)*1000))
        return out
    except Exception as e:
        _log_event("tool", "hdt.get_health_literacy_diabetes@v1", {"user_id": user_id, "purpose": purpose, "error": str(e)}, False, int((_time.time()-t0)*1000))
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
