from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

# Ensure repo root on sys.path when run in different invocation modes
_THIS_FILE = Path(__file__).resolve()
_PROJECT_ROOT = _THIS_FILE.parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from HDT_CORE_INFRASTRUCTURE.users_store import load_users_merged
from HDT_CORE_INFRASTRUCTURE.GAMEBUS_WALK_fetch import fetch_walk_data
from HDT_CORE_INFRASTRUCTURE.GOOGLE_FIT_WALK_fetch import fetch_google_fit_walk_data
from HDT_CORE_INFRASTRUCTURE.GAMEBUS_DIABETES_fetch import fetch_trivia_data, fetch_sugarvita_data

CONFIG_DIR = _PROJECT_ROOT / "config"


def _typed_error(code: str, message: str, *, details: dict | None = None, **extra: Any) -> dict:
    payload: dict[str, Any] = {"error": {"code": code, "message": message}}
    if details:
        payload["error"]["details"] = details
    if extra:
        payload.update(extra)
    return payload


def _strip_bearer_prefix(token: str | None) -> str | None:
    if not token:
        return None
    t = token.strip()
    if t.lower().startswith("bearer "):
        return t.split(None, 1)[1].strip()
    return t


def _parse_datetime_loose(s: str):
    """Parse YYYY-MM-DD, YYYY-MM-DD HH:MM:SS, or ISO-ish timestamps."""
    from datetime import datetime

    st = s.strip()
    if len(st) == 10 and st[4] == "-" and st[7] == "-":
        return datetime.fromisoformat(st)
    if " " in st and "T" not in st:
        try:
            return datetime.strptime(st, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
    st = st.replace("Z", "+00:00")
    return datetime.fromisoformat(st)


def _filter_and_page(records: list[dict], start_date: str | None, end_date: str | None, limit: int | None, offset: int | None) -> list[dict]:
    out = records
    if start_date:
        sd = _parse_datetime_loose(start_date)
        out = [r for r in out if r.get("date") and _parse_datetime_loose(str(r["date"])) >= sd]
    if end_date:
        ed = _parse_datetime_loose(end_date)
        out = [r for r in out if r.get("date") and _parse_datetime_loose(str(r["date"])) <= ed]

    off = max(int(offset or 0), 0)
    if limit is None:
        return out[off:]
    lim = max(int(limit), 0)
    return out[off : off + lim]


def _gamebus_iso(date_str: str | None, *, end: bool = False) -> str | None:
    """Convert YYYY-MM-DD to %Y-%m-%dT%H:%M:%SZ expected by diabetes fetcher."""
    if not date_str:
        return None
    s = date_str.strip()
    if "T" in s and s.endswith("Z"):
        return s
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        return f"{s}T23:59:59Z" if end else f"{s}T00:00:00Z"
    return s


@dataclass(frozen=True)
class Connector:
    connected_application: str
    player_id: str
    auth_bearer: str | None


def _load_users() -> dict[int, dict]:
    return load_users_merged(CONFIG_DIR)


def _find_primary_connector(user: dict, connector_key: str, app: str) -> Connector | None:
    entries = (user.get(connector_key) or [])
    if not isinstance(entries, list):
        return None

    app_norm = (app or "").strip().lower()
    aliases = {app_norm}
    if app_norm in {"google fit", "googlefit", "google_fit"}:
        aliases |= {"google fit", "googlefit", "google_fit"}
    if app_norm in {"gamebus"}:
        aliases |= {"gamebus"}

    for e in entries:
        if not isinstance(e, dict):
            continue
        ca = (e.get("connected_application") or "").strip().lower()
        if ca in aliases:
            pid = e.get("player_id")
            if pid is None:
                continue
            return Connector(
                connected_application=e.get("connected_application") or app,
                player_id=str(pid),
                auth_bearer=_strip_bearer_prefix(e.get("auth_bearer")),
            )
    return None


def _get_user_or_error(user_id: int) -> tuple[dict | None, dict | None]:
    users = _load_users()
    u = users.get(int(user_id))
    if not u:
        return None, _typed_error("unknown_user", f"Unknown user_id={user_id}", user_id=user_id)
    return u, None


def _gamebus_diabetes_connector(u: dict) -> Connector | None:
    # Prefer proper diabetes connector; fallback to GameBus walk connector if config is incomplete.
    c = _find_primary_connector(u, "connected_apps_diabetes_data", "GameBus")
    if c:
        return c

    walk = _find_primary_connector(u, "connected_apps_walk_data", "GameBus")
    if not walk:
        return None

    entries = (u.get("connected_apps_diabetes_data") or [])
    if isinstance(entries, list) and entries:
        first = entries[0] if isinstance(entries[0], dict) else {}
        tok = _strip_bearer_prefix(first.get("auth_bearer"))
        if tok:
            return Connector(connected_application=walk.connected_application, player_id=walk.player_id, auth_bearer=tok)

    return walk


mcp = FastMCP(
    name="HDT-Sources-MCP",
    instructions="Internal MCP façade exposing external sources (GameBus, Google Fit, etc.) as tools.",
)


@mcp.tool(name="healthz@v1")
def healthz() -> dict:
    return {"ok": True}


@mcp.tool(name="sources.status@v1")
def sources_status(user_id: int) -> dict:
    u, err = _get_user_or_error(user_id)
    if err:
        return err

    gb_walk = _find_primary_connector(u, "connected_apps_walk_data", "GameBus")
    gf_walk = _find_primary_connector(u, "connected_apps_walk_data", "Google Fit")
    gb_diab = _find_primary_connector(u, "connected_apps_diabetes_data", "GameBus")

    def _conn_state(c: Connector | None) -> dict:
        if not c:
            return {"configured": False}
        return {
            "configured": True,
            "connected_application": c.connected_application,
            "player_id": c.player_id,
            "has_token": bool(c.auth_bearer and "YOUR_" not in c.auth_bearer),
        }

    return {
        "user_id": user_id,
        "walk": {"gamebus": _conn_state(gb_walk), "googlefit": _conn_state(gf_walk)},
        "diabetes": {"gamebus": _conn_state(gb_diab)},
        "note": "Checks local config only; does not validate tokens upstream.",
    }


@mcp.tool(name="source.gamebus.walk.fetch@v1")
def source_gamebus_walk_fetch(user_id: int, start_date: str | None = None, end_date: str | None = None, limit: int | None = None, offset: int | None = None) -> dict:
    u, err = _get_user_or_error(user_id)
    if err:
        return err

    c = _find_primary_connector(u, "connected_apps_walk_data", "GameBus")
    if not c:
        return _typed_error("not_connected", "User not connected to GameBus for walk data", user_id=user_id)
    if not c.auth_bearer:
        return _typed_error("missing_token", "Missing GameBus auth_bearer for walk connector", user_id=user_id)

    t0 = time.time()
    raw = fetch_walk_data(player_id=c.player_id, auth_bearer=c.auth_bearer)
    if raw is None:
        return _typed_error("upstream_error", "GameBus walk fetch returned no data (upstream error)", user_id=user_id)

    records = _filter_and_page(list(raw), start_date, end_date, limit, offset)
    return {
        "user_id": user_id,
        "source": "GameBus",
        "kind": "walk",
        "records": records,
        "provenance": {"player_id": c.player_id, "retrieved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "ms": int((time.time() - t0) * 1000)},
    }


@mcp.tool(name="source.googlefit.walk.fetch@v1")
def source_googlefit_walk_fetch(user_id: int, start_date: str | None = None, end_date: str | None = None, limit: int | None = None, offset: int | None = None) -> dict:
    u, err = _get_user_or_error(user_id)
    if err:
        return err

    c = _find_primary_connector(u, "connected_apps_walk_data", "Google Fit")
    if not c:
        return _typed_error("not_connected", "User not connected to Google Fit for walk data", user_id=user_id)
    if not c.auth_bearer:
        return _typed_error("missing_token", "Missing Google Fit auth_bearer for walk connector", user_id=user_id)

    t0 = time.time()
    raw = fetch_google_fit_walk_data(player_id=c.player_id, auth_bearer=c.auth_bearer)
    if raw is None:
        return _typed_error("upstream_error", "Google Fit walk fetch returned no data (upstream error)", user_id=user_id)

    records = _filter_and_page(list(raw), start_date, end_date, limit, offset)
    return {
        "user_id": user_id,
        "source": "Google Fit",
        "kind": "walk",
        "records": records,
        "provenance": {"player_id": c.player_id, "retrieved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "ms": int((time.time() - t0) * 1000)},
    }


@mcp.tool(name="source.gamebus.trivia.fetch@v1")
def source_gamebus_trivia_fetch(user_id: int, start_date: str | None = None, end_date: str | None = None) -> dict:
    u, err = _get_user_or_error(user_id)
    if err:
        return err

    c = _gamebus_diabetes_connector(u)
    if not c:
        return _typed_error("not_connected", "User not connected to GameBus for diabetes/trivia data", user_id=user_id)
    if not c.auth_bearer:
        return _typed_error("missing_token", "Missing GameBus auth_bearer for diabetes/trivia connector", user_id=user_id)

    t0 = time.time()
    data, latest = fetch_trivia_data(player_id=c.player_id, start_date=_gamebus_iso(start_date, end=False), end_date=_gamebus_iso(end_date, end=True), auth_bearer=c.auth_bearer)
    if data is None and latest is None:
        return _typed_error("upstream_error", "GameBus trivia fetch returned no data (upstream error)", user_id=user_id)

    return {
        "user_id": user_id,
        "source": "GameBus",
        "kind": "trivia",
        "data": data,
        "latest_activity": latest,
        "provenance": {"player_id": c.player_id, "retrieved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "ms": int((time.time() - t0) * 1000)},
    }


@mcp.tool(name="source.gamebus.sugarvita.fetch@v1")
def source_gamebus_sugarvita_fetch(user_id: int, start_date: str | None = None, end_date: str | None = None) -> dict:
    u, err = _get_user_or_error(user_id)
    if err:
        return err

    c = _gamebus_diabetes_connector(u)
    if not c:
        return _typed_error("not_connected", "User not connected to GameBus for diabetes/sugarvita data", user_id=user_id)
    if not c.auth_bearer:
        return _typed_error("missing_token", "Missing GameBus auth_bearer for diabetes/sugarvita connector", user_id=user_id)

    t0 = time.time()
    data, latest = fetch_sugarvita_data(player_id=c.player_id, start_date=_gamebus_iso(start_date, end=False), end_date=_gamebus_iso(end_date, end=True), auth_bearer=c.auth_bearer)
    if data is None and latest is None:
        return _typed_error("upstream_error", "GameBus sugarvita fetch returned no data (upstream error)", user_id=user_id)

    return {
        "user_id": user_id,
        "source": "GameBus",
        "kind": "sugarvita",
        "data": data,
        "latest_activity": latest,
        "provenance": {"player_id": c.player_id, "retrieved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "ms": int((time.time() - t0) * 1000)},
    }


def main() -> None:
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    mcp.run(transport=transport)


if __name__ == "__main__":
    main()
