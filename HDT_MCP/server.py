from typing import Literal, TypedDict
import os, json, threading, requests
from mcp.server.fastmcp import FastMCP
import time as _time
import datetime as _dt
from pathlib import Path
from dotenv import load_dotenv
import uuid
from contextvars import ContextVar

# Load .env from repo root (…/HDT-agentic-interop/.env)
ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(ENV_PATH)  # replaces your plain load_dotenv()

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR  = REPO_ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
HDT_VAULT_DB = Path(os.getenv("HDT_VAULT_DB", str(DATA_DIR / "lifepod.duckdb")))

# Optional vault support (HDT_VAULT/*.py or a local HDT_MCP/vault.py)
# import the vault module and init it with the path
try:
    from HDT_VAULT import vault as _vault
except Exception:
    try:
        from HDT_MCP import vault as _vault
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
    if not HDT_API_KEY:
        base = {}
    else:
        base = {"X-API-KEY": HDT_API_KEY, "Authorization": f"Bearer {HDT_API_KEY}"}
    base["X-Request-Id"] = _get_request_id()
    return base

def _api_url(path: str) -> str:
    """Robust join of base + path (no double/missing slashes)."""
    return f"{HDT_API_BASE.rstrip('/')}/{path.lstrip('/')}"

def _log_event(
    kind: str,
    name: str,
    args: dict | None = None,
    ok: bool = True,
    ms: int = 0,
    *,
    client_id: str | None = None,
) -> None:

    if _DISABLE_TELEMETRY:
        return
    cid = client_id or MCP_CLIENT_ID
    rid = _get_request_id()
    payload = {"client_id": cid, "request_id": rid}

    if args:
        # caller-supplied fields can override if they pass client_id explicitly
        payload.update(args)

    rec = {
        "ts": _dt.datetime.utcnow().isoformat() + "Z",
        "kind": kind,          # "tool" | "resource"
        "name": name,          # tool/resource identifier
        "client_id": cid,      # top-level for easy grep
        "request_id": rid,
        "args": payload,       # includes client_id too for convenience
        "ok": bool(ok),
        "ms": int(ms),
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

def _apply_policy(purpose: str, tool_name: str, payload: dict, *, client_id: str | None = None):
    """
    Mutates payload in place when allowed (redaction) and returns the payload.
    If denied, returns an error dict and does NOT mutate payload.
    Also records meta (allowed/redactions) in a contextvar for logging/tests.
    """
    rule = _resolve_rule(purpose, tool_name, client_id)
    if not rule.get("allow", True):
        _POLICY_LAST.set({"redactions": 0, "allowed": False, "purpose": purpose, "tool": tool_name})
        return {"error": "denied_by_policy", "purpose": purpose, "tool": tool_name}

    redact_paths = rule.get("redact") or []
    redactions = _redact_inplace(payload, redact_paths) if redact_paths else 0
    _POLICY_LAST.set({"redactions": redactions, "allowed": True, "purpose": purpose, "tool": tool_name})
    return payload

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

# ---------- RESOURCES (context / “read-only”) ----------
# Resources are things the agent can "open" for context, like files/URIs.

@mcp.resource("vault://user/{user_id}/integrated")
def get_integrated_view(user_id: str) -> dict:
    """
    Integrated HDT View (read-mostly):
    1) If vault is enabled, try reading walk records from vault.
    2) If empty, fetch live via tool and (if enabled) write-through to vault.
    3) Compute tiny rollups; apply resource-level policy; log telemetry.
    """
    t0 = _time.time()
    purpose = "analytics"
    src = "vault"  # default; will change to 'live' if we need to fetch

    try:
        # 1) read from vault if available
        records: list[dict] = []
        if HDT_VAULT_ENABLE and _vault is not None:
            try:
                records = _vault.read_walk_records(int(user_id))
            except Exception:
                # non-fatal; fall back to live
                records = []

        # 2) fallback to live fetch (and optional write-through)
        if not records:
            src = "live"
            # call without purpose to stay compatible with older signatures
            walk = tool_get_walk_data(user_id=user_id)

            # normalize to just this user's records
            if isinstance(walk, list):
                leaf = next((r for r in walk if str(r.get("user_id")) == str(user_id)), None)
                records = (leaf or {}).get("data", []) or (leaf or {}).get("records", [])
            elif isinstance(walk, dict):
                records = walk.get("records", walk.get("data", [])) or []

            # write-through to vault for future reads
            if HDT_VAULT_ENABLE and _vault is not None and records:
                try:
                    if hasattr(_vault, "upsert_walk_records"):
                        _vault.upsert_walk_records(int(user_id), records)
                    elif hasattr(_vault, "write_walk"):
                        _vault.write_walk(int(user_id), records, source="api.walk", fetched_at=int(_time.time()))
                except Exception:
                    pass

        # 3) primitive rollups
        days = len(records)
        total_steps = sum(int(r.get("steps", 0) or 0) for r in records)
        avg_steps = int(total_steps / days) if days else 0

        integrated = {
            "user_id": user_id,
            "streams": {
                "walk": {
                    "source": src,                 # "vault" or "live"
                    "count": days,
                    "records": records,
                    "stats": {
                        "days": days,
                        "total_steps": total_steps,
                        "avg_steps": avg_steps
                    },
                }
            },
            "generated_at": int(_time.time()),
        }

        # resource-level policy
        try:
            integrated = _apply_policy(purpose, _INTEGRATED_TOOL_NAME, integrated, client_id=MCP_CLIENT_ID)
            policy_meta = _policy_last_meta()
            _log_event(
                "resource",
                f"vault://user/{user_id}/integrated",
                {"user_id": user_id, "purpose": purpose, "source": src, "records": days,
                 "redactions": policy_meta.get("redactions", 0)},
                True,
                int((_time.time() - t0) * 1000),
            )
        except NameError:
            pass

        return integrated

    except Exception as e:
        _log_event(
            "resource",
            f"vault://user/{user_id}/integrated",
            {"user_id": user_id, "purpose": purpose, "error": str(e)},
            False,
            int((_time.time() - t0) * 1000),
        )
        return {"error": str(e), "user_id": user_id}

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
            {"name": "hdt.get_sugarvita_player_types@v1", "args": ["user_id"]},
            {"name": "hdt.get_health_literacy_diabetes@v1", "args": ["user_id"]},
            {"name": "intervention_time@v1", "args": []},
            {"name": "policy.evaluate@v1", "args": ["purpose","client_id","tool"]},
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
    t0 = _time.time()
    try:
        out = _cached_get("/get_trivia_data", {"user_id": user_id})
        out = _apply_policy("analytics", "hdt.get_trivia_data@v1", out)
        policy_meta = _policy_last_meta()
        _log_event("tool", "hdt.get_trivia_data@v1", {"user_id": user_id, "purpose": "analytics", "redactions": policy_meta.get("redactions", 0)}, True, int((_time.time()-t0)*1000))
        return out
    except Exception as e:
        _log_event("tool", "hdt.get_trivia_data@v1", {"user_id": user_id, "error": str(e)}, False, int((_time.time()-t0)*1000))
        return {"error": str(e), "user_id": user_id}

@mcp.tool(name="hdt.get_sugarvita_data@v1")
def tool_get_sugarvita_data(user_id: str) -> dict:
    t0 = _time.time()
    try:
        out = _cached_get("/get_sugarvita_data", {"user_id": user_id})
        out = _apply_policy("analytics", "hdt.get_sugarvita_data@v1", out, client_id=MCP_CLIENT_ID)
        policy_meta = _policy_last_meta()
        _log_event("tool", "hdt.get_sugarvita_data@v1", {"user_id": user_id, "purpose": "analytics", "redactions": policy_meta.get("redactions", 0)}, True, int((_time.time()-t0)*1000))
        return out
    except Exception as e:
        _log_event("tool", "hdt.get_sugarvita_data@v1", {"user_id": user_id, "error": str(e)}, False, int((_time.time()-t0)*1000))
        return {"error": str(e), "user_id": user_id}

@mcp.tool(name="hdt.get_walk_data@v1")
def tool_get_walk_data(
    user_id: str,
    purpose: str = "analytics",
    # façade options
    limit: int | None = None,
    offset: int | None = None,
    aggregate: bool = False,   # set True to auto-page and merge
    page_limit: int = 200,     # used when aggregate=True
    max_pages: int = 5,        # safety cap when aggregate=True
) -> dict:
    t0 = _time.time()
    persisted = 0
    try:
        def _persist_batch(uid: int, recs: list[dict]) -> None:
            nonlocal persisted
            if HDT_VAULT_ENABLE and _vault is not None and hasattr(_vault, "write_walk") and recs:
                try:
                    _vault.write_walk(uid, recs, source="api.walk", fetched_at=int(_time.time()))
                    persisted += len(recs)
                except Exception:
                    pass

        if aggregate:
            # Auto-paginate using body.page{total,limit,offset}
            collected: list[dict] = []
            cur_offset = 0 if offset is None else int(offset)
            pg = 0
            while True:
                params = {"user_id": user_id, "limit": page_limit, "offset": cur_offset}
                page = _cached_get("/get_walk_data", params)
                envelopes = page if isinstance(page, list) else [page]
                env = envelopes[0] if envelopes else {"user_id": int(user_id), "data": []}
                batch = env.get("data") or env.get("records") or []
                _persist_batch(int(user_id), batch)
                collected.extend(batch)

                meta = env.get("page") or {}
                total = meta.get("total")
                lim   = int(meta.get("limit", page_limit))
                off   = int(meta.get("offset", cur_offset))

                pg += 1
                # stop if no pagination metadata, last page reached, or safety cap
                if total is None or off + lim >= total or pg >= max_pages:
                    break
                cur_offset = off + lim

            out: dict = {
                "user_id": int(user_id),
                "data": collected,
                "page": {
                    "total": len(collected),
                    "limit": len(collected),
                    "offset": 0,
                    "aggregated": True
                }
            }

        else:
            # Simple pass-through (optionally forward limit/offset)
            params = {"user_id": user_id}
            if limit is not None:
                params["limit"] = int(limit)
            if offset is not None:
                params["offset"] = int(offset)

            out = _cached_get("/get_walk_data", params)

            # Persist the batch(es)
            envelopes = out if isinstance(out, list) else [out]
            for env in envelopes:
                uid  = int(env.get("user_id", user_id))
                recs = env.get("data") or env.get("records") or []
                _persist_batch(uid, recs)

        # Optional: upsert the consolidated result for faster future reads
        if HDT_VAULT_ENABLE and _vault is not None and hasattr(_vault, "upsert_walk_records"):
            if isinstance(out, dict):
                recs = out.get("data") or out.get("records") or []
                if recs:
                    try:
                        _vault.upsert_walk_records(int(user_id), recs)
                    except Exception:
                        pass
            elif isinstance(out, list):
                for env in out:
                    uid  = int(env.get("user_id", user_id))
                    recs = env.get("data") or env.get("records") or []
                    if recs:
                        try:
                            _vault.upsert_walk_records(uid, recs)
                        except Exception:
                            pass

        # Apply policy once, on the final out
        out = _apply_policy(purpose, "hdt.get_walk_data@v1", out, client_id=MCP_CLIENT_ID)
        policy_meta = _policy_last_meta()
        _log_event(
            "tool",
            "hdt.get_walk_data@v1",
            {"user_id": user_id, "purpose": purpose, "redactions": policy_meta.get("redactions", 0), "persisted": persisted, "aggregate": aggregate},
            True,
            int((_time.time() - t0) * 1000),
        )
        return out

    except Exception as e:
        _log_event(
            "tool",
            "hdt.get_walk_data@v1",
            {"user_id": user_id, "purpose": purpose, "error": str(e)},
            False,
            int((_time.time() - t0) * 1000),
        )
        return {"error": str(e), "user_id": user_id}


@mcp.tool(name="hdt.get_sugarvita_player_types@v1")
def tool_get_sugarvita_player_types(user_id: str, purpose: Literal["analytics","modeling","coaching"]="analytics") -> dict:
    t0 = _time.time()
    try:
        raw = _cached_get("/get_sugarvita_player_types", {"user_id": user_id})
        out = _apply_policy(purpose, "hdt.get_sugarvita_player_types@v1", raw, client_id=MCP_CLIENT_ID)
        policy_meta = _policy_last_meta()
        _log_event("tool", "hdt.get_sugarvita_player_types@v1", {"user_id": user_id, "purpose": purpose, "redactions": policy_meta.get("redactions", 0)}, True, int((_time.time()-t0)*1000))
        return out
    except Exception as e:
        _log_event("tool", "hdt.get_sugarvita_player_types@v1", {"user_id": user_id, "purpose": purpose, "error": str(e)}, False, int((_time.time()-t0)*1000))
        return {"error": str(e), "user_id": user_id}

@mcp.tool(name="hdt.get_health_literacy_diabetes@v1")
def tool_get_health_literacy_diabetes(user_id: str, purpose: Literal["analytics","modeling","coaching"]="analytics") -> dict:
    t0 = _time.time()
    try:
        raw = _cached_get("/get_health_literacy_diabetes", {"user_id": user_id})
        out = _apply_policy(purpose, "hdt.get_health_literacy_diabetes@v1", raw, client_id=MCP_CLIENT_ID)
        policy_meta = _policy_last_meta()
        _log_event("tool", "hdt.get_health_literacy_diabetes@v1", {"user_id": user_id, "purpose": purpose, "redactions": policy_meta.get("redactions", 0)}, True, int((_time.time()-t0)*1000))
        return out
    except Exception as e:
        _log_event("tool", "hdt.get_health_literacy_diabetes@v1", {"user_id": user_id, "purpose": purpose, "error": str(e)}, False, int((_time.time()-t0)*1000))
        return {"error": str(e), "user_id": user_id}

@mcp.tool(name="policy.evaluate@v1")
def policy_evaluate(purpose: Literal["analytics","modeling","coaching"]="analytics",
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
        return {"error": "vault_disabled", "kept_last_days": days, "deleted_rows": 0}
    deleted = 0
    if hasattr(_vault, "retain_last_days"):
        deleted = int(_vault.retain_last_days(days))
    if hasattr(_vault, "compact"):
        _vault.compact()
    return {"kept_last_days": days, "deleted_rows": deleted}


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
