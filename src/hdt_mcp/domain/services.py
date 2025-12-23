from __future__ import annotations

import time
from typing import Optional, List
from .models import WalkRecord, WalkStreamView, WalkStreamStats, IntegratedView
from .ports import WalkSourcePort, VaultPort


class HDTService:
    """
    Application service: composes ports and encapsulates HDT logic (C1/C2).
    MCP tools call this service and stay ignorant of adapter/API quirks.
    """

    def __init__(self,
                 walk_source: WalkSourcePort,
                 vault: Optional[VaultPort] = None) -> None:
        self.walk_source = walk_source
        self.vault = vault

    # ---- internal helpers -------------------------------------------------
    def _stats(self, records: List[WalkRecord]) -> WalkStreamStats:
        days = len(records)
        total_steps = sum(int(r.steps or 0) for r in records)
        avg_steps = int(total_steps / days) if days else 0
        return WalkStreamStats(days=days, total_steps=total_steps, avg_steps=avg_steps)

    # ---- primary use cases ------------------------------------------------
    def walk_stream(
        self,
        user_id: int,
        prefer_vault: bool = True,
        *,
        from_iso: Optional[str] = None,
        to_iso: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> WalkStreamView:
        """
        Returns a normalized stream of walk records for a user.
        Preference:
          - Try the vault first (read-through) if prefer_vault=True and a vault is provided.
          - Fall back to the live source, and write-through best-effort into the vault.
        The window/limit/offset are passed to ports; if a port ignores them,
        this service can be extended later to post-filter/post-slice.
        """
        # 1) Try vault
        if prefer_vault and self.vault:
            try:
                cached = self.vault.read_walk(
                    user_id,
                    from_iso=from_iso,
                    to_iso=to_iso,
                    limit=limit,
                    offset=offset,
                )
            except Exception:
                cached = []
            if cached:
                return WalkStreamView(source="vault", records=cached, stats=self._stats(cached))

        # 2) Fallback to live
        try:
            live = self.walk_source.fetch_walk(
                user_id,
                from_iso=from_iso,
                to_iso=to_iso,
                limit=limit,
                offset=offset,
            )
        except Exception:
            # Be resilient in absence of upstream API/key
            live = []

        # 3) Write-through (best-effort). Note: writes the retrieved slice/window.
        if self.vault and live:
            try:
                self.vault.write_walk(user_id, live)
            except Exception:
                pass

        return WalkStreamView(source="live", records=live, stats=self._stats(live))

    def integrated_view(self, user_id: int) -> IntegratedView:
        """
        Minimal integrated view that currently includes the walk stream only.
        Extend here when you add more streams (sleep, nutrition, etc.).
        """
        walk = self.walk_stream(user_id=user_id, prefer_vault=True)
        return IntegratedView(
            user_id=int(user_id),
            streams={
                "walk": {
                    "source": walk.source,
                    "count": len(walk.records),
                    "records": [r.model_dump() for r in walk.records],
                    "stats": walk.stats.model_dump(),
                }
            },
            generated_at=int(time.time()),
        )


# (sync_user_walk) was a temporary test shim. Tests now exercise HDTService.walk_stream directly.
