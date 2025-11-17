# HDT_MCP/vault.py
from __future__ import annotations
import sqlite3, json, time, os
from pathlib import Path
from typing import Iterable

_conn: sqlite3.Connection | None = None
_DB_PATH: str | None = None

def _default_db_path() -> str:
    # Prefer test env var, then server env var, then repo/data/lifepod.sqlite
    path = (
        os.getenv("HDT_VAULT_PATH")
        or os.getenv("HDT_VAULT_DB")
        or str(Path(__file__).resolve().parents[1] / "data" / "lifepod.sqlite")
    )
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return path

def init(db_path: str | None = None):
    """
    Initialize the vault. If db_path is omitted, read env (HDT_VAULT_PATH/HDT_VAULT_DB)
    or fallback to repo/data/lifepod.sqlite. Safe to call multiple times.
    """
    global _conn, _DB_PATH
    resolved = db_path or _default_db_path()

    # If already initialized to same path, no-op
    if _conn is not None and _DB_PATH == resolved:
        return

    # Re-init on path change
    if _conn is not None and _DB_PATH != resolved:
        try:
            _conn.close()
        except Exception:
            pass
        _conn = None

    _conn = sqlite3.connect(resolved, check_same_thread=False)
    _conn.execute("""
        CREATE TABLE IF NOT EXISTS walk_records (
            user_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            steps INTEGER,
            raw_json TEXT NOT NULL,
            inserted_at INTEGER NOT NULL,
            PRIMARY KEY (user_id, date)
        )
    """)
    _conn.commit()
    _DB_PATH = resolved

def close():
    """Close the vault connection (handy for tests)."""
    global _conn
    if _conn is not None:
        try:
            _conn.close()
        finally:
            _conn = None

def upsert_walk_records(user_id: int, records: Iterable[dict]) -> int:
    """Idempotent write-through; replaces same (user_id, date). Returns rows written."""
    if _conn is None:
        return 0
    n = 0
    cur = _conn.cursor()
    now = int(time.time())
    for r in records or []:
        dt = r.get("date")
        if not dt:
            continue
        steps = int(r.get("steps") or 0)
        cur.execute(
            "INSERT OR REPLACE INTO walk_records(user_id,date,steps,raw_json,inserted_at)"
            " VALUES (?,?,?,?,?)",
            (int(user_id), str(dt), steps, json.dumps(r, ensure_ascii=False), now),
        )
        n += cur.rowcount
    _conn.commit()
    return n

def read_walk_records(user_id: int) -> list[dict]:
    """Return newest→oldest walk records for user from vault."""
    if _conn is None:
        return []
    cur = _conn.cursor()
    cur.execute(
        "SELECT raw_json FROM walk_records WHERE user_id=? ORDER BY date DESC",
        (int(user_id),),
    )
    return [json.loads(row[0]) for row in cur.fetchall()]

def read_walk_latest(user_id: int, limit: int = 1) -> list[dict]:
    """
    Return the most recent `limit` walk records for the user (newest→oldest).
    Defaults to 1 record. Shape matches `read_walk_records` (list of dicts).
    """
    if _conn is None:
        return []
    cur = _conn.cursor()
    # Dates are stored as ISO-8601 strings (YYYY-MM-DD...), so DESC sorts correctly.
    cur.execute(
        f"SELECT raw_json FROM walk_records WHERE user_id=? ORDER BY date DESC LIMIT {int(limit)}",
        (int(user_id),),
    )
    return [json.loads(row[0]) for row in cur.fetchall()]

# ---- optional: backward-compat shim ---------------------------------------
def write_walk(user_id: int, records: Iterable[dict], *, source: str = "", fetched_at: int | None = None) -> int:
    """Alias for older code paths; delegates to upsert_walk_records."""
    return upsert_walk_records(user_id, records)
