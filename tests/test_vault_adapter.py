from __future__ import annotations
from typing import Any, List

from hdt_mcp.adapters.vault_repo import VaultAdapter, _chunks
from hdt_mcp.domain.models import WalkRecord


class _VaultWithRecords:
    def __init__(self, rows: List[dict]):
        self._rows = rows

    def read_walk_records(self, user_id: int):
        return list(self._rows)


class _VaultWithLatestOnly:
    # No read_walk_records on purpose to trigger fallback
    def __init__(self, latest: dict | None):
        self._latest = latest

    def read_walk_latest(self, user_id: int):
        # Adapter expects a single dict here; we provide one to exercise this path
        return dict(self._latest) if self._latest else None


class _VaultWithUpsert:
    def __init__(self):
        self.calls: list[list[dict]] = []

    def upsert_walk_records(self, user_id: int, rows: List[dict], **kw):
        self.calls.append(rows)
        return len(rows)


class _VaultWithWriteOnly:
    def __init__(self):
        self.calls: list[int] = []
        self._i = 0

    def write_walk(self, user_id: int, rows: List[dict], *, source: str = "", fetched_at: int | None = None):
        # Count calls and simulate an error on the second chunk
        self._i += 1
        self.calls.append(len(rows))
        if self._i == 2:
            raise RuntimeError("transient")
        return len(rows)


def test_read_walk_records_with_limit_and_offset():
    v = _VaultWithRecords([
        {"date": "2025-01-03", "steps": 3},
        {"date": "2025-01-02", "steps": 2},
        {"date": "2025-01-01", "steps": 1},
    ])
    adapter = VaultAdapter(v)
    out = adapter.read_walk(9, limit=1, offset=1)
    assert len(out) == 1
    assert out[0].steps == 2


def test_read_walk_latest_fallback_path():
    v = _VaultWithLatestOnly({"date": "2025-02-01", "steps": 42})
    adapter = VaultAdapter(v)
    out = adapter.read_walk(7)
    assert len(out) == 1 and out[0].steps == 42


def test_write_walk_uses_upsert_when_available():
    v = _VaultWithUpsert()
    adapter = VaultAdapter(v)
    recs = [WalkRecord(date="2025-03-01", steps=10), WalkRecord(date="2025-03-02", steps=20)]
    n = adapter.write_walk(1, recs)
    assert n == 2
    assert v.calls and len(v.calls[0]) == 2


def test_write_walk_fallback_chunking_and_exception_swallow():
    v = _VaultWithWriteOnly()
    adapter = VaultAdapter(v)
    # 1005 records -> chunks: 500, 500, 5 (second chunk will raise)
    recs = [WalkRecord(date=f"2025-04-{(i%28)+1:02d}", steps=i) for i in range(1005)]
    n = adapter.write_walk(2, recs)
    # Only 1st and 3rd chunks counted: 500 + 5
    assert n == 505
    assert v.calls and v.calls[0] == 500


def test_chunks_helper_splits_correctly():
    items = [WalkRecord(date="2025-01-01", steps=i) for i in range(7)]
    sizes = [len(chunk) for chunk in _chunks(items, 3)]
    assert sizes == [3, 3, 1]
