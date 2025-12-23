from __future__ import annotations

from typing import Protocol, runtime_checkable, Optional, List
from .models import WalkRecord

@runtime_checkable
class WalkSourcePort(Protocol):
    """
    A live/remote source of walk data (e.g., your Flask API or direct adapter).
    It returns *normalized* domain records, not raw envelopes.
    """
    def fetch_walk(
        self,
        user_id: int,
        *,
        from_iso: Optional[str] = None,
        to_iso: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> List[WalkRecord]:
        ...
        # Implementations should:
        # - Call the upstream (HTTP, SDK, etc.)
        # - Normalize any envelope to List[WalkRecord]
        # - Respect the optional window/limit/offset if supported,
        #   otherwise return a superset and let the service filter.


@runtime_checkable
class VaultPort(Protocol):
    """
    A persistence abstraction for user-owned storage of walk data.
    Typically backed by your vault module; returns normalized domain records.
    """
    def read_walk(
        self,
        user_id: int,
        *,
        from_iso: Optional[str] = None,
        to_iso: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> List[WalkRecord]:
        ...
        # Implementations may ignore window/limit/offset if not supported;
        # the service can filter/slice as a fallback.

    def write_walk(
        self,
        user_id: int,
        records: List[WalkRecord],
    ) -> int:
        ...
        # Should be idempotent per (user_id, date) if your store supports it.
