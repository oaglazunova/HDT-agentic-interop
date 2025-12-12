from __future__ import annotations
from typing import Optional, List, Any, Dict
import time

from HDT_MCP.domain.models import WalkRecord
from HDT_MCP.domain.ports import VaultPort


class VaultAdapter(VaultPort):
    """
    Wraps your underlying vault module (duckdb/sqlite) with a domain-friendly interface.
    The provided `vault_mod` should be the already-imported HDT_MCP.vault module.
    """

    def __init__(self, vault_mod: Any) -> None:
        self.v = vault_mod

    def read_walk(
        self,
        user_id: int,
        *,
        from_iso: Optional[str] = None,
        to_iso: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> List[WalkRecord]:
        # Use the broadest read your vault supports, then (optionally) slice/filter here.
        rows: List[Dict] = []
        if hasattr(self.v, "read_walk_records"):
            rows = self.v.read_walk_records(int(user_id)) or []
        elif hasattr(self.v, "read_walk_latest"):
            # Fallback: single latest row → wrap
            latest = self.v.read_walk_latest(int(user_id))
            rows = [latest] if latest else []
        else:
            rows = []

        # TODO: If needed, filter by from_iso/to_iso here.
        recs = [WalkRecord.model_validate(r) for r in rows if isinstance(r, dict)]

        # Optional: apply limit/offset locally if vault does not support them.
        if offset:
            recs = recs[offset:]
        if limit is not None:
            recs = recs[:limit]

        return recs

    def write_walk(self, user_id: int, records: List[WalkRecord]) -> int:
        if not records:
            return 0

        # Prefer upsert; otherwise fall back to write_walk signature
        if hasattr(self.v, "upsert_walk_records"):
            return self.v.upsert_walk_records(int(user_id), [r.model_dump() for r in records])

        # Fallback to a bulk write that also wants metadata
        n = 0
        if hasattr(self.v, "write_walk"):
            now = int(time.time())
            for chunk in _chunks(records, 500):
                try:
                    n += self.v.write_walk(
                        int(user_id),
                        [r.model_dump() for r in chunk],
                        source="domain.walk",
                        fetched_at=now,
                    )
                except Exception:
                    pass
        return n


def _chunks(lst: List[WalkRecord], size: int):
    for i in range(0, len(lst), size):
        yield lst[i:i + size]
