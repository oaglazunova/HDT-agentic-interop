import os, time
from HDT_MCP import vault

def test_retain_last_days(tmp_path, monkeypatch):
    monkeypatch.setenv("HDT_VAULT_PATH", str(tmp_path / "v.db"))
    vault.init()

    today = time.strftime("%Y-%m-%d")
    old   = "2024-01-01"
    uid = 42

    vault.write_walk(uid, [{"date": old, "steps": 100}, {"date": today, "steps": 200}])
    deleted = vault.retain_last_days(30_000, uid)  # keep almost everything
    assert deleted == 0

    deleted = vault.retain_last_days(30, uid)      # keep ~last month → old should go
    assert deleted >= 1
    latest = vault.read_walk_records(uid)
    assert all(rec["date"] >= time.strftime("%Y-%m-%d", time.gmtime(time.time() - 30*86400)) for rec in latest)
