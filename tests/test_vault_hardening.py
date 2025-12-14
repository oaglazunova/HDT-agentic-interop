import os
from pathlib import Path
from datetime import date, timedelta
from hdt_mcp import vault

def test_idempotent_upsert(tmp_path):
    db = tmp_path / "v.db"
    vault.init(str(db))

    # Same record twice -> still one row because of PK(user_id,date)
    rec = {"date": "2025-11-01", "steps": 100}
    n1 = vault.write_walk(7, [rec], source="test")
    n2 = vault.write_walk(7, [rec], source="test")
    assert n1 >= 1
    assert n2 >= 1  # REPLACE still counts as a write

    rows = vault.read_walk_records(7)
    assert len([r for r in rows if r.get("date") == "2025-11-01"]) == 1
    assert rows[0]["steps"] == 100

def test_read_order_newest_first(tmp_path):
    db = tmp_path / "v.db"
    vault.init(str(db))

    # three sequential days
    today = date.today()
    recs = [
        {"date": (today - timedelta(days=2)).isoformat(), "steps": 1},
        {"date": (today - timedelta(days=1)).isoformat(), "steps": 2},
        {"date": today.isoformat(), "steps": 3},
    ]
    vault.write_walk(5, recs, source="test")

    latest = vault.read_walk_latest(5, limit=2)
    assert len(latest) == 2
    # newest→oldest
    assert latest[0]["steps"] == 3
    assert latest[1]["steps"] == 2
