from hdt_mcp.adapters.vault_repo import VaultAdapter
from hdt_mcp.domain.models import WalkRecord


def test_vault_adapter_read_walk_limit_offset():
    class VaultMod:
        def read_walk_records(self, user_id: int):
            return [
                {"date": "2025-01-01", "steps": 1},
                {"date": "2025-01-02", "steps": 2},
                {"date": "2025-01-03", "steps": 3},
            ]

    adapter = VaultAdapter(VaultMod())
    recs = adapter.read_walk(1, limit=1, offset=1)
    assert len(recs) == 1
    assert isinstance(recs[0], WalkRecord)
    assert recs[0].date == "2025-01-02"
    assert recs[0].steps == 2


def test_vault_adapter_write_walk_prefers_upsert():
    calls = {"n": 0}

    class VaultMod:
        def upsert_walk_records(self, user_id: int, rows):
            calls["n"] += 1
            return len(rows)

    adapter = VaultAdapter(VaultMod())
    n = adapter.write_walk(1, [WalkRecord(date="2025-01-01", steps=10)])
    assert n == 1
    assert calls["n"] == 1
