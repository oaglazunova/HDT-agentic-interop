from __future__ import annotations
from typing import Protocol, List
from .models import WalkRecord


class WalkSourcePort(Protocol):
    """Read walk records from some source (GameBus, Google Fit, etc.)."""
    def fetch_walk(self, user_id: int) -> List[WalkRecord]: ...


class VaultPort(Protocol):
    """Read/write user-centric records to the local HDT vault."""
    def read_walk(self, user_id: int) -> List[WalkRecord]: ...
    def write_walk(self, user_id: int, records: List[WalkRecord]) -> int: ...
