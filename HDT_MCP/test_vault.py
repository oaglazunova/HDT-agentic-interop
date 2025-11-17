from HDT_MCP import vault

def test_vault_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("HDT_VAULT_PATH", str(tmp_path/"v.db"))
    vault.init()
    n = vault.write_walk(3, [{"date":"2025-11-01","steps":123}], source="test")
    assert n >= 1
    rows = vault.read_walk_latest(3)
    assert rows and rows[-1]["steps"] == 123
