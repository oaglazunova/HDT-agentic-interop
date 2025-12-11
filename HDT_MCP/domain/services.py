from __future__ import annotations
import time
from typing import Optional, List
from .models import WalkRecord, WalkStreamView, WalkStreamStats, IntegratedView
from .ports import WalkSourcePort, VaultPort


class HDTService:
    """
    Application service: composes ports and encapsulates HDT logic.
    Tools and transports use this, not raw adapters.
    """

    def __init__(self,
                 walk_source: WalkSourcePort,
                 vault: Optional[VaultPort] = None) -> None:
        self.walk_source = walk_source
        self.vault = vault

    def _stats(self, records: List[WalkRecord]) -> WalkStreamStats:
        days = len(records)
        total_steps = sum(int(r.steps or 0) for r in records)
        avg_steps = int(total_steps / days) if days else 0
        return WalkStreamStats(days=days, total_steps=total_steps, avg_steps=avg_steps)

    def walk_stream(self, user_id: int, prefer_vault: bool = True) -> WalkStreamView:
        # 1) try vault
        if prefer_vault and self.vault:
            try:
                cached = self.vault.read_walk(user_id)
            except Exception:
                cached = []
            if cached:
                return WalkStreamView(source="vault", records=cached, stats=self._stats(cached))

        # 2) fallback to live
        live = self.walk_source.fetch_walk(user_id)
        # write-through into vault (best-effort)
        if self.vault and live:
            try:
                self.vault.write_walk(user_id, live)
            except Exception:
                pass
        return WalkStreamView(source="live", records=live, stats=self._stats(live))

    def integrated_view(self, user_id: int) -> IntegratedView:
        walk = self.walk_stream(user_id=user_id, prefer_vault=True)
        return IntegratedView(
            user_id=int(user_id),
            streams={"walk": {
                "source": walk.source,
                "count": len(walk.records),
                "records": [r.model_dump() for r in walk.records],
                "stats": walk.stats.model_dump(),
            }},
            generated_at=int(time.time())
        )
