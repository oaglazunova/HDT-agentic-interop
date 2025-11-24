# HDT_MCP/vault.py
from __future__ import annotations
import sqlite3, json, time, os
from pathlib import Path
from typing import Iterable, Optional

_conn: sqlite3.Connection | None = None
_DB_PATH: str | None = None

def _default_db_path() -> str:
    path = (
        os.getenv("HDT_VAULT_PATH")
        or os.getenv("HDT_VAULT_DB")
        or str(Path(__file__).resolve().parents[1] / "data" / "lifepod.sqlite")
    )
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return path

def _exec(conn: sqlite3.Connection, sql: str) -> None:
    conn.execute(sql)

def init(db_path: str | None = None):
    """
    Initialize the vault. If db_path is omitted, read env (HDT_VAULT_PATH/HDT_VAULT_DB)
    or fallback to repo/data/lifepod.sqlite. Safe to call multiple times.
    Enforces WAL mode, NORMAL sync, and a reasonable busy timeout.
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

    # Open + pragmas
    _conn = sqlite3.connect(resolved, check_same_thread=False)
    # Busy timeout to reduce "database is locked" errors under contention
    _exec(_conn, "PRAGMA busy_timeout=5000")
    # WAL journal; better concurrency for reads while writes happen
    _exec(_conn, "PRAGMA journal_mode=WAL")
    # Reasonable durability/perf tradeoff for app data
    _exec(_conn, "PRAGMA synchronous=NORMAL")

    # Schema
    _exec(_conn, """
        CREATE TABLE IF NOT EXISTS walk_records (
            user_id     INTEGER NOT NULL,
            date        TEXT    NOT NULL,  -- ISO-8601 (YYYY-MM-DD or YYYY-MM-DD HH:MM:SS)
            steps       INTEGER,
            raw_json    TEXT    NOT NULL,
            inserted_at INTEGER NOT NULL,
            PRIMARY KEY (user_id, date)
        )
    """)

    # Optional helper index: speeds WHERE user_id=? ORDER BY date DESC
    _exec(_conn, "CREATE INDEX IF NOT EXISTS idx_walk_user_date_desc ON walk_records(user_id, date DESC)")
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
            "INSERT OR REPLACE INTO walk_records(user_id,date,steps,raw_json,inserted_at) VALUES (?,?,?,?,?)",
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
    cur.execute(
        f"SELECT raw_json FROM walk_records WHERE user_id=? ORDER BY date DESC LIMIT {int(limit)}",
        (int(user_id),),
    )
    return [json.loads(row[0]) for row in cur.fetchall()]

# ---- Retention & compaction helpers ----------------------------------------

def retain_last_days(days: int, user_id: Optional[int] = None) -> int:
    """
    Keep only the last `days` of data (based on ISO date prefix). Returns rows deleted.
    Uses substr(date,1,10) so it works with 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM:SS'.
    """
    if _conn is None or days <= 0:
        return 0
    # Threshold date (YYYY-MM-DD)
    # On Windows, time.gmtime() raises OSError for negative timestamps.
    # Clamp to the Unix epoch to avoid platform errors for very large `days`.
    try:
        t = time.time() - days * 86400
        if t < 0:
            t = 0
        cutoff = time.strftime("%Y-%m-%d", time.gmtime(t))
    except (OverflowError, OSError, ValueError):  # defensive: fall back to epoch
        cutoff = "1970-01-01"
    cur = _conn.cursor()
    if user_id is None:
        cur.execute("DELETE FROM walk_records WHERE substr(date,1,10) < ?", (cutoff,))
    else:
        cur.execute(
            "DELETE FROM walk_records WHERE user_id=? AND substr(date,1,10) < ?",
            (int(user_id), cutoff),
        )
    deleted = cur.rowcount or 0
    _conn.commit()
    return deleted

def compact():
    """
    Compact the database file.
    With WAL, first checkpoint, then VACUUM to reclaim space.
    """
    if _conn is None:
        return
    try:
        _exec(_conn, "PRAGMA wal_checkpoint(TRUNCATE)")
        _exec(_conn, "VACUUM")
    except Exception:
        # Best effort; safe to ignore during normal ops
        pass

# ---- optional: backward-compat shim ---------------------------------------

def write_walk(user_id: int, records: Iterable[dict], *, source: str = "", fetched_at: int | None = None) -> int:
    """Alias for older code paths; delegates to upsert_walk_records."""
    return upsert_walk_records(user_id, records)
