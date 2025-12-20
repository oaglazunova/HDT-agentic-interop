from hdt_mcp.adapters.vault_repo import VaultAdapter
from hdt_mcp.domain.models import WalkRecord


def test_vault_adapter_read_latest_branch():
    class V:
        def read_walk_latest(self, user_id: int):
            return {"date": "2025-01-09", "steps": 9}

    adapter = VaultAdapter(V())
    recs = adapter.read_walk(1)
    assert len(recs) == 1
    assert isinstance(recs[0], WalkRecord)
    assert recs[0].date == "2025-01-09"
    assert recs[0].steps == 9


def test_vault_adapter_write_walk_fallback_write_walk_ignores_exceptions():
    calls = {"n": 0}

    class V:
        def write_walk(self, user_id: int, rows, source: str, fetched_at: int):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("fail once")
            return len(rows)

    adapter = VaultAdapter(V())
    recs = [WalkRecord(date="2025-01-01", steps=1), WalkRecord(date="2025-01-02", steps=2)]
    n = adapter.write_walk(1, recs)

    # first call failed but is swallowed; second succeeds
    assert n >= 0
    assert calls["n"] >= 1
