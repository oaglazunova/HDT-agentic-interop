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

def _ensure_schema(conn: sqlite3.Connection) -> None:
    # Base table + index (idempotent)
    _exec(conn, """
        CREATE TABLE IF NOT EXISTS walk_records (
            user_id     INTEGER NOT NULL,
            date        TEXT    NOT NULL,  -- ISO-8601 (YYYY-MM-DD or YYYY-MM-DD HH:MM:SS)
            steps       INTEGER,
            raw_json    TEXT    NOT NULL,
            inserted_at INTEGER NOT NULL,
            PRIMARY KEY (user_id, date)
        )
    """)
    _exec(conn, "CREATE INDEX IF NOT EXISTS idx_walk_user_date_desc ON walk_records(user_id, date DESC)")

def init(db_path: str | None = None):
    """
    Initialize the vault. If db_path is omitted, read env (HDT_VAULT_PATH/HDT_VAULT_DB)
    or fallback to repo/data/lifepod.sqlite. Safe to call multiple times.
    Enforces WAL mode, NORMAL sync, FK, and a reasonable busy timeout.
    """
    global _conn, _DB_PATH
    resolved = db_path or _default_db_path()

    if _conn is not None and _DB_PATH == resolved:
        return

    if _conn is not None and _DB_PATH != resolved:
        _conn.close()
        _conn = None

    _conn = sqlite3.connect(resolved, check_same_thread=False)
    _exec(_conn, "PRAGMA busy_timeout=5000")
    _exec(_conn, "PRAGMA journal_mode=WAL")
    _exec(_conn, "PRAGMA synchronous=NORMAL")
    _exec(_conn, "PRAGMA foreign_keys=ON")

    _ensure_schema(_conn)
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

def upsert_walk_records(user_id: int, records: Iterable[dict], **kw) -> int:
    """Alias maintained for compatibility; delegates to write_walk."""
    return write_walk(user_id, records, **kw)


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
    """
    if _conn is None:
        return []
    lim = max(1, int(limit))
    cur = _conn.cursor()
    cur.execute(
        "SELECT raw_json FROM walk_records WHERE user_id=? ORDER BY date DESC LIMIT ?",
        (int(user_id), lim),
    )
    return [json.loads(row[0]) for row in cur.fetchall()]


def read_walk_between(user_id: int, start_date: str, end_date: str) -> list[dict]:
    """
    Inclusive range on ISO dates (YYYY-MM-DD[ HH:MM:SS]).
    Returns oldest→newest within the range.
    """
    if _conn is None:
        return []
    cur = _conn.cursor()
    cur.execute(
        """
        SELECT raw_json
        FROM walk_records
        WHERE user_id = ?
          AND date >= ?
          AND date <= ?
        ORDER BY date ASC
        """,
        (int(user_id), str(start_date), str(end_date)),
    )
    return [json.loads(row[0]) for row in cur.fetchall()]



# ---- Helpers ----------------------------------------

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
    _exec(_conn, "PRAGMA wal_checkpoint(TRUNCATE)")
    _exec(_conn, "VACUUM")

def count_walk_records(user_id: int | None = None) -> int:
    if _conn is None:
        return 0
    cur = _conn.cursor()
    if user_id is None:
        cur.execute("SELECT COUNT(*) FROM walk_records")
    else:
        cur.execute("SELECT COUNT(*) FROM walk_records WHERE user_id=?", (int(user_id),))
    return int(cur.fetchone()[0])

def purge_user(user_id: int) -> int:
    """Delete all rows for a user. Returns rows deleted."""
    if _conn is None:
        return 0
    cur = _conn.cursor()
    cur.execute("DELETE FROM walk_records WHERE user_id=?", (int(user_id),))
    deleted = cur.rowcount or 0
    _conn.commit()
    return deleted

def get_db_path() -> str | None:
    return _DB_PATH


# ---- optional: backward-compat shim ---------------------------------------

def write_walk(
    user_id: int,
    records: Iterable[dict],
    *,
    source: str = "",
    fetched_at: int | None = None,
) -> int:
    """Insert or update walk records for user in vault. Returns rows affected.

    Parameters `source` and `fetched_at` are accepted for forward/backward
    compatibility but are not stored separately in the current schema.
    """
    if _conn is None:
        return 0
    now = int(time.time())
    n = 0
    with _conn:  # ensures a single transaction & commit
        cur = _conn.cursor()
        for r in records or []:
            dt = r.get("date")
            if not dt:
                continue
            steps = int(r.get("steps") or 0)
            cur.execute(
                "INSERT OR REPLACE INTO walk_records(user_id,date,steps,raw_json,inserted_at) VALUES (?,?,?,?,?)",
                (int(user_id), str(dt), steps, json.dumps(r, ensure_ascii=False), now),
            )
            n += cur.rowcount or 0
    return n
