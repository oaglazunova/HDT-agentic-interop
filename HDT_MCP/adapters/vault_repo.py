from __future__ import annotations
from typing import List, Any
from ..domain.models import WalkRecord
from ..domain.ports import VaultPort


class VaultRepo(VaultPort):
    """
    Thin wrapper around your HDT_MCP.vault module.
    """

    def __init__(self, vault_module: Any):
        self._v = vault_module

    def read_walk(self, user_id: int) -> List[WalkRecord]:
        if not self._v or not hasattr(self._v, "read_walk_records"):
            return []
        raw = self._v.read_walk_records(int(user_id)) or []
        return [WalkRecord.model_validate(r) for r in raw]

    def write_walk(self, user_id: int, records: List[WalkRecord]) -> int:
        if not self._v:
            return 0
        # Prefer upsert_walk_records if present; fallback to write_walk
        if hasattr(self._v, "upsert_walk_records"):
            return int(self._v.upsert_walk_records(int(user_id), [r.model_dump() for r in records]))
        if hasattr(self._v, "write_walk"):
            return int(self._v.write_walk(int(user_id), [r.model_dump() for r in records], source="domain"))
        return 0
