import asyncio
import importlib


def test_walk_fetch_vault_only_returns_seeded_records(monkeypatch, tmp_path):
    # 1) Force-enable vault for this test (isolated, deterministic)
    monkeypatch.setenv("HDT_VAULT_ENABLE", "1")
    monkeypatch.setenv("HDT_VAULT_PATH", str(tmp_path / "test_vault.db"))

    # 2) Import AFTER env is set (important if module reads env on import)
    from HDT_MCP import vault_store
    importlib.reload(vault_store)

    from HDT_MCP.mcp_governor import HDTGovernor

    # 3) Seed
    vault_store.init()
    vault_store.upsert_walk(
        1,
        [
            {"date": "2025-12-10", "steps": 1234, "distance_meters": 900, "duration": 1800, "kcalories": 70},
            {"date": "2025-12-11", "steps": 2222, "distance_meters": 1500, "duration": 2200, "kcalories": 95},
        ],
        source="gamebus",
    )

    # 4) Read via Governor (vault-only)
    gov = HDTGovernor()
    out = asyncio.run(
        gov.fetch_walk(
            user_id=1,
            limit=10,
            prefer="gamebus",
            prefer_data="vault",
        )
    )

    assert isinstance(out, dict)
    assert "error" not in out
    assert out.get("source") == "Vault"
    assert len(out.get("records", [])) >= 2
