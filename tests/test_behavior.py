from HDT_MCP.models.behavior import behavior_strategy
from HDT_MCP import vault

def test_behavior_from_vault(tmp_path, monkeypatch):
    # Isolate a temp vault file
    monkeypatch.setenv("HDT_VAULT_ENABLE", "1")
    monkeypatch.setenv("HDT_VAULT_PATH", str(tmp_path/"v.db"))
    vault.init()  # uses env path

    # Seed a few records
    from datetime import date, timedelta
    today = date.today()
    records = [
        {"date": (today - timedelta(days=2)).isoformat(), "steps": 4000},
        {"date": (today - timedelta(days=1)).isoformat(), "steps": 6000},
        {"date": today.isoformat(), "steps": 5000},
    ]
    vault.upsert_walk_records(1, records)

    plan = behavior_strategy(1, days=7)
    assert isinstance(plan.get("avg_steps"), int)
    assert plan["avg_steps"] > 0
    assert isinstance(plan["message"], str)
    assert isinstance(plan["bct_refs"], list)
