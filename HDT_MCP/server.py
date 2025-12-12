from typing import Literal, TypedDict
import os, json, threading, requests
from mcp.server.fastmcp import FastMCP
import time as _time
import datetime as _dt
from pathlib import Path
from dotenv import load_dotenv
import uuid
from contextvars import ContextVar
import sys

# Ensure project root is on sys.path when run via direct file path
_THIS_FILE = Path(__file__).resolve()
_PROJECT_ROOT = _THIS_FILE.parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from HDT_MCP.models.behavior import behavior_strategy as _behavior_strategy
from HDT_MCP.models.behavior import _headers as _base_headers
from HDT_MCP.domain.services import HDTService
from HDT_MCP.adapters.api_walk import ApiWalkAdapter
from HDT_MCP.adapters.vault_repo import VaultAdapter
from HDT_MCP.constants import (
    LANE_ANALYTICS,
    LANE_MODELING,
    LANE_COACHING,
)
import copy

# --- unified error helper -----------------------------------------------------
def _typed_error(code: str, message: str, *, details: dict | None = None, **extra: object) -> dict:
    """Return a standardized error envelope used by MCP:
    {"error": {"code": code, "message": message, "details": {...}}, ...extra}
    """
    err: dict = {"error": {"code": code, "message": message}}
    if details:
        err["error"]["details"] = details
    if extra:
        err.update(extra)
    return err


# Load .env from repo root (…/HDT-agentic-interop/.env)
ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(ENV_PATH)  # replaces your plain load_dotenv()

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR  = REPO_ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
HDT_VAULT_DB = Path(os.getenv("HDT_VAULT_DB", str(DATA_DIR / "lifepod.duckdb")))
HDT_VAULT = os.getenv("HDT_VAULT", "duckdb")

# Optional vault support (HDT_VAULT/*.py or a local HDT_MCP/vault.py)
# Resolve dynamically to avoid hard import errors when package is absent.
import importlib
_vault = None
try:
    _vault = importlib.import_module("HDT_VAULT.vault")
except Exception:
    try:
        _vault = importlib.import_module("HDT_MCP.vault")
    except Exception:
        _vault = None

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"

MCP_CLIENT_ID = os.getenv("MCP_CLIENT_ID", "MODEL_DEVELOPER_1")

# Your existing API that the MCP façade talks to (your Flask/whatever service).
HDT_API_BASE = os.environ.get("HDT_API_BASE", "http://localhost:5000")
# If your API uses a key/header, grab it from env. Adjust header name if needed.
HDT_API_KEY  = os.environ.get("HDT_API_KEY", os.environ.get("MODEL_DEVELOPER_1_API_KEY", ""))  # reuse your .env
print(f"[HDT-MCP] HDT_API_BASE={HDT_API_BASE}  HDT_API_KEY={'<set>' if HDT_API_KEY else '<missing>'}")

_ENABLE_POLICY = (os.getenv("HDT_ENABLE_POLICY_TOOLS", "0") or "").strip().lower() in {"1","true","yes","on"}
print(f"[HDT-MCP] POLICY_TOOLS={_ENABLE_POLICY} (HDT_ENABLE_POLICY_TOOLS={os.getenv('HDT_ENABLE_POLICY_TOOLS')})")

#_TELEMETRY_DIR = Path(__file__).parent / "telemetry"
_TELEMETRY_DIR = Path(
    os.getenv("HDT_TELEMETRY_DIR", str(Path(__file__).parent / "telemetry"))
)
_TELEMETRY_DIR.mkdir(parents=True, exist_ok=True)
_DISABLE_TELEMETRY = (os.getenv("HDT_DISABLE_TELEMETRY","0").lower() in ("1","true","yes"))

_cache: dict[tuple[str, tuple], tuple[float, dict]] = {}
_CACHE_TTL = int(os.getenv("HDT_CACHE_TTL", "15"))
_RETRY_MAX = int(os.getenv("HDT_RETRY_MAX", "2"))

_INTEGRATED_TOOL_NAME = "vault.integrated@v1"

# --- policy file location & cache signature ---
_POLICY_PATH: Path = Path(os.getenv("HDT_POLICY_PATH", str(CONFIG_DIR / "policy.json")))
_POLICY_CACHE: dict | None = None
_POLICY_SIG: tuple[int, int] | None = None  # (st_mtime_ns, st_size)
_POLICIES_LOCK = threading.Lock()
_POLICY_OVERRIDE: dict | None = None  # test fixture can set this
# last policy meta for the *current* call (thread/async-safe)
_POLICY_LAST = ContextVar(
    "policy_last",
    default={"redactions": 0, "allowed": True, "purpose": "", "tool": ""},
)

REDACT_TOKEN = "***redacted***"


# Where user -> allowed_clients lives (keep in config/)
_USER_PERMS_PATH = CONFIG_DIR / "user_permissions.json"

HDT_VAULT_ENABLE = os.getenv("HDT_VAULT_ENABLE", "0").lower() in ("1", "true", "yes")

if HDT_VAULT_ENABLE and _vault is not None:
    try:
        _vault.init(db_path=str(HDT_VAULT_DB))
        print(f"[HDT-MCP] Vault initialized at {HDT_VAULT_DB}")
    except Exception as e:
        print(f"[HDT-MCP] Vault init failed, disabling vault: {e}")
        _vault = None
else:
    print("[HDT-MCP] Vault disabled or not available")

_request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)

# Create the MCP server façade (B0: MCP Core / Orchestrator)
mcp = FastMCP(
    name="HDT-MCP",
    instructions="Façade exposing HDT data & decisions as MCP tools/resources.",
    website_url="https://github.com/oaglazunova/Interoperable-and-modular-HDT-system-prototype",
)

# Adapters for domain will be initialized after helper definitions
_cache_lock = threading.Lock()
# --- helpers ----------------------------------------------------------------
def _new_request_id() -> str:
    return uuid.uuid4().hex

def _get_request_id() -> str:
    rid = _request_id_ctx.get()
    if not rid:
        rid = _new_request_id()
        _request_id_ctx.set(rid)
    return rid

def _set_request_id(rid: str | None):
    if rid:
        _request_id_ctx.set(rid)

def _headers() -> dict[str, str]:
    """Build standard outbound HTTP headers once, adding request correlation.

    Delegates base auth headers to the shared builder in models.behavior,
    then adds the current X-Request-Id for traceability.
    """
    base = dict(_base_headers())  # copy to avoid mutating shared dict
    base["X-Request-Id"] = _get_request_id()
    return base

def _api_url(path: str) -> str:
    """Robust join of base + path (no double/missing slashes)."""
    return f"{HDT_API_BASE.rstrip('/')}/{path.lstrip('/')}"

# Recreate adapters and domain service now that helpers are defined
walk_adapter = ApiWalkAdapter(
    base_url=HDT_API_BASE,
    headers_provider=_headers,
)
vault_repo = VaultAdapter(_vault) if (HDT_VAULT_ENABLE and _vault is not None) else None

# Domain service
_domain = HDTService(walk_source=walk_adapter, vault=vault_repo)

def _log_event(
    kind: str,
    name: str,
    args: dict | None = None,
    ok: bool = True,
    ms: int = 0,
    *,
    client_id: str | None = None,
    corr_id: str | None = None,
) -> None:

    if _DISABLE_TELEMETRY:
        return
    cid = client_id or MCP_CLIENT_ID
    rid = _get_request_id()
    # Copy only caller-supplied args. Avoid duplicating top-level fields
    # like client_id or request_id inside the args payload to reduce log size.
    payload = {} if args is None else dict(args)

    rec = {
        "ts": _dt.datetime.utcnow().isoformat() + "Z",
        "kind": kind,          # "tool" | "resource"
        "name": name,          # tool/resource identifier
        "client_id": cid,      # top-level for easy grep
        "request_id": rid,
        "corr_id": corr_id or rid,
        "args": payload,
        "ok": bool(ok),
        "ms": int(ms),
    }
    with open(_TELEMETRY_DIR / "mcp-telemetry.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")


def _hdt_get(path: str, params: dict | None=None) -> dict:
    url = _api_url(path)
    last = None
    rid = _get_request_id()                         # stable across retries
    for attempt in range(1, _RETRY_MAX + 2):
        try:
            hdrs = _headers()
            hdrs["X-Request-Id"] = rid  # force same id on each retry
            r = requests.get(
                url, headers=hdrs, params=params or {}, timeout=30
            )
            r.raise_for_status()
            # prefer server-issued id if present (keeps your logs consistent end-to-end)
            server_rid = r.headers.get("X-Request-Id")
            if server_rid:
                _set_request_id(server_rid)
                rid = server_rid
            return r.json()
        except Exception as e:
            last = e
            if attempt <= _RETRY_MAX:
                _time.sleep(0.5 * attempt)  # simple backoff
            else:
                raise last



def _cached_get(path: str, params: dict | None=None) -> dict:
    """Return a cached copy of GET JSON.

    Guarantees immutability of cached entries by:
    - Returning deep copies to callers
    - Storing deep copies under the cache key
    so downstream in-place mutations (e.g., policy redaction) never corrupt the cache.
    """
    key = (path, tuple(sorted((params or {}).items())))
    now = _time.time()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < _CACHE_TTL:
            return copy.deepcopy(hit[1])
    data = _hdt_get(path, params)
    with _cache_lock:
        _cache[key] = (now, copy.deepcopy(data))
    return copy.deepcopy(data)


# --- policy/redaction helpers ------------------------------------------------
def _load_policy_file() -> dict:
    try:
        with _POLICY_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def _redact_inplace(doc: object, paths: list[str]) -> int:
    """
    In-place redaction by dotted paths. Returns number of fields redacted.
    Supports lists, e.g. "users.email" will redact every element's "email".
    """
    total = 0
    for p in paths or []:
        parts = p.split(".") if isinstance(p, str) else list(p)
        total += _redact_path(doc, parts)
    return total

def _redact_path(node: object, parts: list[str]) -> int:
    if not parts:
        return 0
    key, rest = parts[0], parts[1:]

    # If the current node is a list, apply the same path to each element.
    if isinstance(node, list):
        c = 0
        for item in node:
            c += _redact_path(item, parts)
        return c

    # Only descend through dicts
    if not isinstance(node, dict) or key not in node:
        return 0

    if not rest:
        # Terminal segment => redact
        # Count this as 1 redaction even if already the token
        node[key] = REDACT_TOKEN
        return 1

    return _redact_path(node[key], rest)

def _policy() -> dict:
    global _POLICY_CACHE, _POLICY_SIG
    if _POLICY_OVERRIDE is not None:
        return _POLICY_OVERRIDE

    try:
        st = _POLICY_PATH.stat()
    except FileNotFoundError:
        with _POLICIES_LOCK:
            _POLICY_CACHE, _POLICY_SIG = {}, None
        return {}

    sig = (st.st_mtime_ns, st.st_size)  # nanosecond resolution + size
    with _POLICIES_LOCK:
        if _POLICY_CACHE is None or _POLICY_SIG != sig:
            _POLICY_CACHE = _load_policy_file()
            _POLICY_SIG = sig
        return _POLICY_CACHE or {}

def _merge_rule(base: dict, override: dict | None) -> dict:
    out = dict(base or {})
    if override:
        out.update(override)
    # always normalize keys
    out.setdefault("allow", True)
    out.setdefault("redact", [])
    return out


def _resolve_rule(purpose: str, tool_name: str, client_id: str | None) -> dict:
    pol = _policy()
    rule = _merge_rule({}, pol.get("defaults", {}).get(purpose))
    if client_id:
        rule = _merge_rule(rule, pol.get("clients", {}).get(client_id, {}).get(purpose))
    rule = _merge_rule(rule, pol.get("tools", {}).get(tool_name, {}).get(purpose))
    return rule


def _apply_policy_metrics(
    purpose: str,
    tool_name: str,
    payload: dict,
    *,
    client_id: str | None = None,
):
    """
    Convenience wrapper for tests/metrics: applies policy and returns a tuple
    of (result_payload, redactions_count).
    """
    # Use safe application to protect any shared/cached payloads from in-place mutation
    result = _apply_policy_safe(purpose, tool_name, payload, client_id=client_id)
    meta = _policy_last_meta() or {}
    return result, int(meta.get("redactions", 0))

#To force reload (e.g., after having edited the file very quickly, or in tests)
def _policy_reset_cache() -> None:
    global _POLICY_CACHE, _POLICY_SIG, _POLICY_OVERRIDE
    with _POLICIES_LOCK:
        _POLICY_CACHE = None
        _POLICY_SIG = None
        # leave _POLICY_OVERRIDE as-is unless the tests need to toggle it

def _load_user_permissions() -> dict:
    try:
        with _USER_PERMS_PATH.open("r", encoding="utf-8") as f:
            return json.load(f) or {}
    except FileNotFoundError:
        return {}

def _policy_last_meta() -> dict:
    """For logging/tests: returns last policy meta (redactions, allowed, purpose, tool)."""
    return _POLICY_LAST.get()

def _apply_policy(purpose: str, tool_name: str, payload: dict, *, client_id: str | None = None):
    """
    Mutates payload in place when allowed (redaction) and returns the payload.
    If denied, returns an error dict and does NOT mutate payload.
    Also records meta (allowed/redactions) in a contextvar for logging/tests.
    """
    rule = _resolve_rule(purpose, tool_name, client_id)
    if not rule.get("allow", True):
        _POLICY_LAST.set({"redactions": 0, "allowed": False, "purpose": purpose, "tool": tool_name})
        return _typed_error(
            "denied_by_policy",
            "Access denied by policy",
            purpose=purpose,
            tool=tool_name,
        )

    redact_paths = rule.get("redact") or []
    redactions = _redact_inplace(payload, redact_paths) if redact_paths else 0
    _POLICY_LAST.set({"redactions": redactions, "allowed": True, "purpose": purpose, "tool": tool_name})
    return payload

def _apply_policy_safe(purpose: str, tool_name: str, payload: dict, *, client_id: str | None = None):
    """Apply policy to a deep copy to avoid mutating cached/shared objects."""
    clone = copy.deepcopy(payload)
    return _apply_policy(purpose, tool_name, clone, client_id=client_id)



# ---------- RESOURCES (context / “read-only”) ----------
# Resources are things the agent can "open" for context, like files/URIs.

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
            # Primary domain-shaped tools
            {"name": "hdt.walk.stream@v1", "args": ["user_id", "prefer", "start", "end"]},
            {"name": "hdt.walk.stats@v1", "args": ["user_id", "start", "end"]},

            # Other tools
            {"name": "healthz@v1", "args": []},
            {"name": "hdt.get_trivia_data@v1", "args": ["user_id"]},
            {"name": "hdt.get_sugarvita_data@v1", "args": ["user_id"]},
            {"name": "hdt.get_sugarvita_player_types@v1", "args": ["user_id"]},
            {"name": "hdt.get_health_literacy_diabetes@v1", "args": ["user_id"]},
            {"name": "behavior_strategy@v1", "args": ["user_id"]},
            {"name": "intervention_time@v1", "args": []},
            {"name": "policy.evaluate@v1", "args": ["purpose", "client_id", "tool"]},
        ]
    }

@mcp.resource("telemetry://recent/{n}")
def telemetry_recent(n: int = 50) -> dict:
    p = _TELEMETRY_DIR / "mcp-telemetry.jsonl"
    if not p.exists():
        return {"records": []}
    lines = p.read_text(encoding="utf-8").splitlines()[-n:]
    return {"records": [json.loads(x) for x in lines]}


@mcp.resource("vault://user/{user_id}/integrated")
def get_integrated_view(user_id: str) -> dict:
    t0 = _time.time()
    purpose = "analytics"
    try:
        # Use domain-integrated view (vault-first)
        view = _domain.integrated_view(int(user_id))
        integrated = view.model_dump() if hasattr(view, "model_dump") else {
            "user_id": view.user_id,
            "streams": view.streams,
            "generated_at": view.generated_at,
        }
        integrated = _apply_policy_safe(purpose, _INTEGRATED_TOOL_NAME, integrated, client_id=MCP_CLIENT_ID)
        days = integrated.get("streams", {}).get("walk", {}).get("stats", {}).get("days", 0)
        _log_event("resource", f"vault://user/{user_id}/integrated",
                   {"user_id": user_id, "purpose": purpose, "records": days},
                   True, int((_time.time()-t0)*1000))
        return integrated
    except Exception as e:
        _log_event("resource", f"vault://user/{user_id}/integrated",
                   {"user_id": user_id, "purpose": purpose, "error": str(e)},
                   False, int((_time.time()-t0)*1000))
        return _typed_error("internal", str(e), user_id=user_id)



# --- 2) TOOLS (actions / compute) -------------------------------------------
# Tools are callables with typed params; MCP auto-generates JSON Schemas (B1).

@mcp.tool(name="healthz@v1")
def tool_healthz() -> dict:
    return {"ok": True}

@mcp.tool(name="hdt.get_trivia_data@v1")
def tool_get_trivia_data(user_id: str) -> dict:
    t0 = _time.time()
    try:
        out = _cached_get("/get_trivia_data", {"user_id": user_id})
        out = _apply_policy_safe(LANE_ANALYTICS, "hdt.get_trivia_data@v1", out)
        policy_meta = _policy_last_meta()
        _log_event("tool", "hdt.get_trivia_data@v1", {"user_id": user_id, "purpose": LANE_ANALYTICS, "redactions": policy_meta.get("redactions", 0)}, True, int((_time.time()-t0)*1000))
        return out
    except Exception as e:
        _log_event("tool", "hdt.get_trivia_data@v1", {"user_id": user_id, "error": str(e)}, False, int((_time.time()-t0)*1000))
        return _typed_error("internal", str(e), user_id=user_id)

@mcp.tool(name="hdt.get_sugarvita_data@v1")
def tool_get_sugarvita_data(user_id: str) -> dict:
    t0 = _time.time()
    try:
        out = _cached_get("/get_sugarvita_data", {"user_id": user_id})
        out = _apply_policy_safe(LANE_ANALYTICS, "hdt.get_sugarvita_data@v1", out, client_id=MCP_CLIENT_ID)
        policy_meta = _policy_last_meta()
        _log_event("tool", "hdt.get_sugarvita_data@v1", {"user_id": user_id, "purpose": LANE_ANALYTICS, "redactions": policy_meta.get("redactions", 0)}, True, int((_time.time()-t0)*1000))
        return out
    except Exception as e:
        _log_event("tool", "hdt.get_sugarvita_data@v1", {"user_id": user_id, "error": str(e)}, False, int((_time.time()-t0)*1000))
        return _typed_error("internal", str(e), user_id=user_id)


@mcp.tool(name="hdt.get_sugarvita_player_types@v1")
def tool_get_sugarvita_player_types(user_id: str, purpose: Literal["analytics","modeling","coaching"]=LANE_ANALYTICS) -> dict:
    t0 = _time.time()
    try:
        raw = _cached_get("/get_sugarvita_player_types", {"user_id": user_id})
        out = _apply_policy_safe(purpose, "hdt.get_sugarvita_player_types@v1", raw, client_id=MCP_CLIENT_ID)
        policy_meta = _policy_last_meta()
        _log_event("tool", "hdt.get_sugarvita_player_types@v1", {"user_id": user_id, "purpose": purpose, "redactions": policy_meta.get("redactions", 0)}, True, int((_time.time()-t0)*1000))
        return out
    except Exception as e:
        _log_event("tool", "hdt.get_sugarvita_player_types@v1", {"user_id": user_id, "purpose": purpose, "error": str(e)}, False, int((_time.time()-t0)*1000))
        return _typed_error("internal", str(e), user_id=user_id)

@mcp.tool(name="hdt.get_health_literacy_diabetes@v1")
def tool_get_health_literacy_diabetes(user_id: str, purpose: Literal["analytics","modeling","coaching"]=LANE_ANALYTICS) -> dict:
    t0 = _time.time()
    try:
        raw = _cached_get("/get_health_literacy_diabetes", {"user_id": user_id})
        out = _apply_policy_safe(purpose, "hdt.get_health_literacy_diabetes@v1", raw, client_id=MCP_CLIENT_ID)
        policy_meta = _policy_last_meta()
        _log_event("tool", "hdt.get_health_literacy_diabetes@v1", {"user_id": user_id, "purpose": purpose, "redactions": policy_meta.get("redactions", 0)}, True, int((_time.time()-t0)*1000))
        return out
    except Exception as e:
        _log_event("tool", "hdt.get_health_literacy_diabetes@v1", {"user_id": user_id, "purpose": purpose, "error": str(e)}, False, int((_time.time()-t0)*1000))
        return _typed_error("internal", str(e), user_id=user_id)

@mcp.tool(name="policy.evaluate@v1")
def policy_evaluate(purpose: Literal["analytics","modeling","coaching"]=LANE_ANALYTICS,
                    client_id: str | None = None,
                    tool: str | None = None) -> dict:
    pol = _policy()  # ← not _load_policy()
    eff = pol.get("defaults", {}).get(purpose, {"allow": True, "redact": []})
    if client_id and (c := pol.get("clients", {}).get(client_id, {}).get(purpose)):
        eff = {**eff, **c}
    if tool and (t := pol.get("tools", {}).get(tool, {}).get(purpose)):
        eff = {**eff, **t}
    return {"purpose": purpose, "allow": eff.get("allow", True), "redact": eff.get("redact", [])}

@mcp.tool(name="consent.status@v1")
def consent_status(client_id: str | None = None) -> dict:
    """
    Return which users and permissions the given client_id is allowed to access.
    Falls back to MCP_CLIENT_ID from env if not provided.
    """
    cid = client_id or MCP_CLIENT_ID
    perms = _load_user_permissions()
    users = []
    for uid, p in (perms or {}).items():
        allowed = (p.get("allowed_clients") or {}).get(cid, [])
        try:
            users.append({"user_id": int(uid), "allowed_permissions": sorted(set(allowed))})
        except Exception:
            users.append({"user_id": uid, "allowed_permissions": sorted(set(allowed))})
    return {"client_id": cid, "users": users}

@mcp.tool(name="policy.reload@v1")
def policy_reload() -> dict:
    """
    Clear policy cache and reload from disk (config/policy.json).
    Useful during tests or live editing.
    """
    _policy_reset_cache()
    # Touch it once so subsequent calls are hot
    _ = _policy()
    return {"reloaded": True}

@mcp.tool(name="vault.maintain@v1")
def vault_maintain(days: int = 60) -> dict:
    if not (_vault and HDT_VAULT_ENABLE):
        return _typed_error("vault_disabled", "Vault is disabled", kept_last_days=days, deleted_rows=0)
    deleted = 0
    if hasattr(_vault, "retain_last_days"):
        deleted = int(_vault.retain_last_days(days))
    if hasattr(_vault, "compact"):
        _vault.compact()
    return {"kept_last_days": days, "deleted_rows": deleted}

@mcp.tool(name="behavior_strategy@v1")
def tool_behavior_strategy(user_id: str, purpose: str = LANE_COACHING) -> dict:
    t0 = _time.time()
    try:
        plan = _behavior_strategy(int(user_id))
        # Apply coaching-lane policy (lets you redact if needed)
        plan = _apply_policy_safe(purpose, "behavior_strategy@v1", plan, client_id=MCP_CLIENT_ID)
        _log_event("tool", "behavior_strategy@v1",
                   {"user_id": user_id, "purpose": purpose, "avg_steps": plan.get("avg_steps", 0)},
                   True, int((_time.time()-t0)*1000))
        return plan
    except Exception as e:
        _log_event("tool", "behavior_strategy@v1",
                   {"user_id": user_id, "purpose": purpose, "error": str(e)},
                   False, int((_time.time()-t0)*1000))
        return _typed_error("internal", str(e), user_id=user_id)


@mcp.tool(name="hdt.walk.stream@v1")
def hdt_walk_stream(user_id: int,
                    prefer: str = "auto",
                    start: str | None = None,
                    end: str | None = None) -> dict:
    """
    Domain-shaped walk stream for agents.
    prefer: "vault" | "live" | "auto"
    """
    # Validate prefer input early to avoid surprising defaults
    if prefer not in ("auto", "vault", "live"):
        return _typed_error(
            "bad_request",
            "prefer must be one of: auto, vault, live",
            prefer=prefer,
        )
    # Map prefer string to service's boolean flag
    prefer_vault = True if prefer in ("auto", "vault") else False
    view = _domain.walk_stream(
        int(user_id),
        prefer_vault=prefer_vault,
        from_iso=start,
        to_iso=end,
    )
    payload = {
        "user_id": int(user_id),
        "records": [
            {
                "date": r.date,  # already ISO string
                "steps": r.steps,
                "distance_meters": r.distance_meters,
                "duration": r.duration,
                "kcalories": r.kcalories,
            } for r in view.records
        ],
        "source": view.source,
        "stats": view.stats.model_dump() if hasattr(view.stats, "model_dump") else {
            "days": view.stats.days,
            "total_steps": view.stats.total_steps,
            "avg_steps": view.stats.avg_steps,
        },
    }
    return _apply_policy_safe("analytics", "hdt.walk.stream@v1", payload, client_id=MCP_CLIENT_ID)


@mcp.tool(name="hdt.walk.stats@v1")
def hdt_walk_stats(user_id: int,
                   start: str | None = None,
                   end: str | None = None) -> dict:
    # Prefer vault when available
    view = _domain.walk_stream(int(user_id), prefer_vault=True, from_iso=start, to_iso=end)
    stats = view.stats.model_dump() if hasattr(view.stats, "model_dump") else {
        "days": view.stats.days,
        "total_steps": view.stats.total_steps,
        "avg_steps": view.stats.avg_steps,
    }
    return _apply_policy_safe("analytics", "hdt.walk.stats@v1", {"user_id": user_id, "stats": stats}, client_id=MCP_CLIENT_ID)



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
