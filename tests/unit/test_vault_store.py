import importlib
import pytest


@pytest.mark.parametrize("value,expected", [
    ("1", True),
    ("true", True),
    ("yes", True),
    ("on", True),
    ("0", False),
    ("false", False),
    ("", False),
])
def test_enabled_env(monkeypatch, value, expected):
    import hdt_mcp.vault_store as vs
    monkeypatch.setenv("HDT_VAULT_ENABLE", value)
    assert vs.enabled() is expected


def test_upsert_and_fetch_prefers_source(tmp_path, monkeypatch):
    import hdt_mcp.vault_store as vs
    importlib.reload(vs)

    db = tmp_path / "vault.sqlite"
    vs.init(str(db))

    user_id = 1

    # Same date in two sources: prefer_source should win
    vs.upsert_walk(
        user_id,
        [{"date": "2025-01-01", "steps": 100, "distance_meters": 10.0}],
        source="gamebus",
    )
    vs.upsert_walk(
        user_id,
        [{"date": "2025-01-01", "steps": 999, "distance_meters": 99.0}],
        source="googlefit",
    )

    # Another date only in googlefit
    vs.upsert_walk(
        user_id,
        [{"date": "2025-01-02", "steps": 200}],
        source="googlefit",
    )

    out = vs.fetch_walk(user_id, prefer_source="gamebus")
    assert out["user_id"] == user_id
    assert out["kind"] == "walk"
    assert len(out["records"]) == 2

    rec1 = out["records"][0]
    rec2 = out["records"][1]

    assert rec1["date"] == "2025-01-01"
    assert rec1["source"] == "gamebus"      # preferred wins
    assert rec1["steps"] == 100

    assert rec2["date"] == "2025-01-02"
    assert rec2["source"] == "googlefit"
    assert rec2["steps"] == 200

    assert out["stats"]["days"] == 2
    assert out["stats"]["total_steps"] == 300


def test_fetch_limit_offset(tmp_path):
    import hdt_mcp.vault_store as vs
    importlib.reload(vs)

    db = tmp_path / "vault.sqlite"
    vs.init(str(db))

    user_id = 7
    vs.upsert_walk(user_id, [{"date": "2025-01-01", "steps": 10}], source="gamebus")
    vs.upsert_walk(user_id, [{"date": "2025-01-02", "steps": 20}], source="gamebus")
    vs.upsert_walk(user_id, [{"date": "2025-01-03", "steps": 30}], source="gamebus")

    out = vs.fetch_walk(user_id, prefer_source="gamebus", limit=1, offset=1)
    assert [r["date"] for r in out["records"]] == ["2025-01-02"]


def test_maintain_deletes_old_rows(tmp_path, monkeypatch):
    import hdt_mcp.vault_store as vs
    importlib.reload(vs)

    db = tmp_path / "vault.sqlite"
    vs.init(str(db))

    user_id = 1

    # Insert with "old" time
    monkeypatch.setattr(vs.time, "time", lambda: 0)
    vs.upsert_walk(user_id, [{"date": "2025-01-01", "steps": 10}], source="gamebus")

    # Run maintain with "future" time so cutoff deletes the old row
    monkeypatch.setattr(vs.time, "time", lambda: 200 * 86400)
    res = vs.maintain(days=1)
    assert res["ok"] is True
    assert res["deleted_rows"] >= 1

    out = vs.fetch_walk(user_id, prefer_source="gamebus")
    assert out["records"] == []
