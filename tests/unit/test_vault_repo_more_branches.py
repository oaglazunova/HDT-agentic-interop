from hdt_mcp.adapters.vault_repo import VaultAdapter
from hdt_mcp.domain.models import WalkRecord


def test_vault_adapter_read_walk_latest_branch():
    class V:
        def read_walk_latest(self, user_id: int):
            return {"date": "2025-01-09", "steps": 9}

    adapter = VaultAdapter(V())
    recs = adapter.read_walk(1)
    assert len(recs) == 1
    assert isinstance(recs[0], WalkRecord)
    assert recs[0].date == "2025-01-09"
    assert recs[0].steps == 9


def test_vault_adapter_write_walk_fallback_chunks_and_swallow_exceptions():
    calls = {"n": 0}

    class V:
        def write_walk(self, user_id: int, rows, source: str, fetched_at: int):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("fail first chunk")
            return len(rows)

    adapter = VaultAdapter(V())

    # >500 records to exercise chunking
    recs = [WalkRecord(date=f"2025-01-{(i % 28) + 1:02d}", steps=i) for i in range(600)]
    n = adapter.write_walk(1, recs)

    assert calls["n"] >= 2  # chunked
    assert n >= 0           # exception swallowed, still returns int


def test_vault_adapter_write_walk_empty_returns_zero():
    class V:
        def write_walk(self, *a, **k):
            raise AssertionError("should not be called")

    adapter = VaultAdapter(V())
    assert adapter.write_walk(1, []) == 0
