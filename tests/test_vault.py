from HDT_MCP import vault

def test_vault_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("HDT_VAULT_PATH", str(tmp_path/"v.db"))
    vault.init()
    n = vault.write_walk(3, [{"date":"2025-11-01","steps":123}], source="test")
    assert n >= 1
    rows = vault.read_walk_latest(3)
    assert rows and rows[-1]["steps"] == 123

def test_request_id_echo(client):
    # no header -> server generates one
    res = client.get("/healthz")
    rid1 = res.headers.get("X-Request-Id")
    assert rid1 and len(rid1) >= 8

    # provided header -> server echoes it unchanged
    res2 = client.get("/healthz", headers={"X-Request-Id": "abc123"})
    assert res2.headers.get("X-Request-Id") == "abc123"