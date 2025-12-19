from __future__ import annotations
from typing import List, Optional

from hdt_mcp.domain.services import HDTService
from hdt_mcp.domain.models import WalkRecord


class FakeVault:
    def __init__(self, primed: List[WalkRecord] | None = None) -> None:
        self._primed = list(primed or [])
        self.read_calls: int = 0
        self.write_calls: int = 0
        self.last_written: List[WalkRecord] | None = None

    def read_walk(
        self,
        user_id: int,
        *,
        from_iso: Optional[str] = None,
        to_iso: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> List[WalkRecord]:
        self.read_calls += 1
        return list(self._primed)

    def write_walk(self, user_id: int, records: List[WalkRecord]) -> int:
        self.write_calls += 1
        self.last_written = list(records)
        return len(records)


class FakeLive:
    def __init__(self, records: List[WalkRecord]) -> None:
        self._records = list(records)
        self.fetch_calls: int = 0

    def fetch_walk(
        self,
        user_id: int,
        *,
        from_iso: Optional[str] = None,
        to_iso: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> List[WalkRecord]:
        self.fetch_calls += 1
        return list(self._records)


def _wr(date: str, steps: int) -> WalkRecord:
    return WalkRecord.model_validate({"date": date, "steps": steps})


def test_walk_stream_prefers_vault_when_present():
    cached = [_wr("2025-11-01", 111)]
    vault = FakeVault(primed=cached)
    live = FakeLive(records=[_wr("2025-11-02", 222)])

    svc = HDTService(walk_source=live, vault=vault)
    out = svc.walk_stream(user_id=42, prefer_vault=True)

    assert out.source == "vault"
    assert [r.steps for r in out.records] == [111]
    assert live.fetch_calls == 0, "Should not call live when vault has data"
    assert vault.write_calls == 0, "Should not write-through when returning cached data"


def test_walk_stream_falls_back_to_live_and_writes_through():
    # Vault is empty -> should fetch from live, return 'live', and write to vault once
    vault = FakeVault(primed=[])
    fetched = [_wr("2025-11-03", 333), _wr("2025-11-04", 444)]
    live = FakeLive(records=fetched)

    svc = HDTService(walk_source=live, vault=vault)
    out = svc.walk_stream(user_id=7, prefer_vault=True)

    assert out.source == "live"
    assert [r.steps for r in out.records] == [333, 444]
    assert live.fetch_calls == 1
    assert vault.write_calls == 1
    assert vault.last_written is not None
    assert [r.steps for r in vault.last_written] == [333, 444]
