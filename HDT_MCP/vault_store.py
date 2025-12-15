from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


_LOCK = threading.Lock()
_INIT = False
_DB_PATH: Path | None = None


def enabled() -> bool:
    return (os.getenv("HDT_VAULT_ENABLE", "0") or "").strip().lower() in {"1", "true", "yes", "on"}


def _default_db_path() -> Path:
    repo_root = Path(__file__).resolve().parents[1]
    data_dir = repo_root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    # Prefer HDT_VAULT_PATH (your .env), fallback to HDT_VAULT_DB if you ever add it
    p = os.getenv("HDT_VAULT_PATH") or os.getenv("HDT_VAULT_DB") or str(data_dir / "hdt_vault.sqlite")
    return (repo_root / p).resolve() if not Path(p).is_absolute() else Path(p)


def init(db_path: str | None = None) -> str:
    global _INIT, _DB_PATH
    _DB_PATH = Path(db_path) if db_path else _default_db_path()
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    with _LOCK:
        con = sqlite3.connect(str(_DB_PATH))
        try:
            con.execute("PRAGMA journal_mode=WAL;")
            con.execute("PRAGMA synchronous=NORMAL;")
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS walk_records (
                    user_id INTEGER NOT NULL,
                    date TEXT NOT NULL,            -- YYYY-MM-DD
                    source TEXT NOT NULL,          -- "gamebus" | "googlefit"
                    steps INTEGER,
                    distance_meters REAL,
                    duration REAL,
                    kcalories REAL,
                    raw_json TEXT,
                    inserted_at INTEGER NOT NULL,  -- unix epoch seconds
                    PRIMARY KEY (user_id, date, source)
                );
                """
            )
            con.execute("CREATE INDEX IF NOT EXISTS idx_walk_user_date ON walk_records(user_id, date);")
            con.commit()
        finally:
            con.close()

    _INIT = True
    return str(_DB_PATH)


def _ensure_init() -> None:
    if not _INIT:
        init()


def _norm_date(s: Any) -> Optional[str]:
    if s is None:
        return None
    t = str(s).strip()
    if not t:
        return None
    if "T" in t:
        t = t.split("T", 1)[0]
    return t[:10]  # YYYY-MM-DD


def upsert_walk(user_id: int, records: List[Dict[str, Any]], *, source: str) -> Dict[str, Any]:
    _ensure_init()
    assert _DB_PATH is not None

    src = (source or "").strip().lower() or "unknown"
    now = int(time.time())

    rows = []
    for r in records or []:
        d = _norm_date(r.get("date") or r.get("day") or r.get("timestamp"))
        if not d:
            continue

        steps = int(r.get("steps") or r.get("step_count") or 0)
        dist = float(r.get("distance_meters") or r.get("distance") or 0.0)
        dur = float(r.get("duration") or r.get("duration_seconds") or 0.0)
        kcal = float(r.get("kcalories") or r.get("calories") or 0.0)
        raw = json.dumps(r, ensure_ascii=False)

        rows.append((int(user_id), d, src, steps, dist, dur, kcal, raw, now))

    t0 = time.perf_counter()
    with _LOCK:
        con = sqlite3.connect(str(_DB_PATH))
        try:
            if rows:
                con.executemany(
                    """
                    INSERT INTO walk_records
                      (user_id, date, source, steps, distance_meters, duration, kcalories, raw_json, inserted_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(user_id, date, source) DO UPDATE SET
                      steps=excluded.steps,
                      distance_meters=excluded.distance_meters,
                      duration=excluded.duration,
                      kcalories=excluded.kcalories,
                      raw_json=excluded.raw_json,
                      inserted_at=excluded.inserted_at
                    """,
                    rows,
                )
                con.commit()
        finally:
            con.close()

    ms = int((time.perf_counter() - t0) * 1000)
    return {"ok": True, "stored": len(rows), "source": src, "ms": ms, "db": str(_DB_PATH)}


def fetch_walk(
    user_id: int,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
    prefer_source: str = "gamebus",
) -> Dict[str, Any]:
    _ensure_init()
    assert _DB_PATH is not None

    sd = _norm_date(start_date)
    ed = _norm_date(end_date)
    prefer = (prefer_source or "gamebus").strip().lower()

    lim = None if limit is None else max(int(limit), 0)
    off = max(int(offset or 0), 0)

    where = ["user_id = ?"]
    params: List[Any] = [int(user_id)]
    if sd:
        where.append("date >= ?")
        params.append(sd)
    if ed:
        where.append("date <= ?")
        params.append(ed)
    where_sql = " AND ".join(where)

    base_sql = f"""
      SELECT user_id, date, source, steps, distance_meters, duration, kcalories, inserted_at
      FROM walk_records
      WHERE {where_sql}
    """

    t0 = time.perf_counter()
    with _LOCK:
        con = sqlite3.connect(str(_DB_PATH))
        try:
            con.row_factory = sqlite3.Row

            stats_sql = f"""
              WITH ranked AS (
                SELECT *,
                  ROW_NUMBER() OVER (
                    PARTITION BY user_id, date
                    ORDER BY
                      CASE WHEN source = ? THEN 0 ELSE 1 END,
                      inserted_at DESC
                  ) AS rn
                FROM ({base_sql})
              )
              SELECT
                COUNT(*) AS days,
                COALESCE(SUM(steps), 0) AS total_steps,
                COALESCE(AVG(steps), 0.0) AS avg_steps
              FROM ranked
              WHERE rn = 1
            """
            stats_row = con.execute(stats_sql, [prefer] + params).fetchone()
            stats = {
                "days": int(stats_row["days"] or 0),
                "total_steps": int(stats_row["total_steps"] or 0),
                "avg_steps": float(stats_row["avg_steps"] or 0.0),
            }

            fetch_sql = f"""
              WITH ranked AS (
                SELECT *,
                  ROW_NUMBER() OVER (
                    PARTITION BY user_id, date
                    ORDER BY
                      CASE WHEN source = ? THEN 0 ELSE 1 END,
                      inserted_at DESC
                  ) AS rn
                FROM ({base_sql})
              )
              SELECT user_id, date, source, steps, distance_meters, duration, kcalories, inserted_at
              FROM ranked
              WHERE rn = 1
              ORDER BY date
            """

            fetch_params: List[Any] = [prefer] + params
            if lim is not None:
                fetch_sql += " LIMIT ? OFFSET ?"
                fetch_params += [lim, off]
            else:
                fetch_sql += " LIMIT -1 OFFSET ?"
                fetch_params += [off]

            rows = con.execute(fetch_sql, fetch_params).fetchall()
        finally:
            con.close()

    ms = int((time.perf_counter() - t0) * 1000)

    records = []
    sources = set()
    for r in rows:
        sources.add(str(r["source"]))
        records.append(
            {
                "date": str(r["date"]),
                "steps": int(r["steps"] or 0),
                "distance_meters": float(r["distance_meters"] or 0.0),
                "duration": float(r["duration"] or 0.0),
                "kcalories": float(r["kcalories"] or 0.0),
                "source": str(r["source"]),
            }
        )

    return {
        "user_id": int(user_id),
        "source": "Vault",
        "kind": "walk",
        "records": records,
        "stats": stats,
        "vault_sources": sorted(sources),
        "provenance": {"db": str(_DB_PATH), "ms": ms},
    }


def maintain(days: int = 60) -> Dict[str, Any]:
    _ensure_init()
    assert _DB_PATH is not None

    keep_days = max(int(days), 0)
    cutoff = int(time.time()) - keep_days * 86400

    t0 = time.perf_counter()
    with _LOCK:
        con = sqlite3.connect(str(_DB_PATH))
        try:
            before = con.execute("SELECT COUNT(*) FROM walk_records").fetchone()[0]
            con.execute("DELETE FROM walk_records WHERE inserted_at < ?", (cutoff,))
            after = con.execute("SELECT COUNT(*) FROM walk_records").fetchone()[0]
            con.commit()
            deleted = int(before - after)
        finally:
            con.close()

    ms = int((time.perf_counter() - t0) * 1000)
    return {"ok": True, "kept_last_days": keep_days, "deleted_rows": deleted, "ms": ms, "db": str(_DB_PATH)}
