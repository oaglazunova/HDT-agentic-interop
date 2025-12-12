from __future__ import annotations
from typing import Optional, List, Callable, Dict, Any
import requests

from HDT_MCP.domain.models import WalkRecord
from HDT_MCP.domain.ports import WalkSourcePort


class ApiWalkAdapter(WalkSourcePort):
    """
    Calls your Flask API (/get_walk_data?user_id=...) and normalizes envelopes
    into List[WalkRecord] for the domain layer.
    """

    def __init__(
        self,
        base_url: str,
        headers_provider: Optional[Callable[[], Dict[str, str]]] = None,
        timeout_sec: int = 30,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.headers_provider = headers_provider or (lambda: {})
        self.timeout = timeout_sec

    def _normalize(self, user_id: int, payload: Any) -> List[WalkRecord]:
        """
        Accepts either a list of envelopes or a dict, and returns List[WalkRecord].
        """
        records: List[WalkRecord] = []

        def to_record(d: Dict[str, Any]) -> WalkRecord:
            # Pydantic v2: model_validate will coerce types where reasonable
            return WalkRecord.model_validate({
                "date": d.get("date"),
                "steps": d.get("steps", 0),
                "distance_meters": d.get("distance_meters"),
                "duration": d.get("duration"),
                "kcalories": d.get("kcalories"),
            })

        if isinstance(payload, list):
            # Find matching user envelope
            env = next((e for e in payload if int(e.get("user_id", -1)) == int(user_id)), None)
            data = (env or {}).get("data", []) or (env or {}).get("records", [])
            records = [to_record(x) for x in (data or []) if isinstance(x, dict)]
        elif isinstance(payload, dict):
            data = payload.get("data", []) or payload.get("records", [])
            records = [to_record(x) for x in (data or []) if isinstance(x, dict)]
        else:
            # Unknown shape → return empty
            records = []

        return records

    def fetch_walk(
        self,
        user_id: int,
        *,
        from_iso: Optional[str] = None,
        to_iso: Optional[str] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> List[WalkRecord]:
        # Build query; your current API filters by ?user_id; others are currently ignored server-side
        params = {"user_id": str(user_id)}
        if from_iso:
            params["from"] = from_iso
        if to_iso:
            params["to"] = to_iso
        if limit is not None:
            params["limit"] = str(limit)
        if offset is not None:
            params["offset"] = str(offset)

        url = f"{self.base_url}/get_walk_data"
        r = requests.get(url, headers=self.headers_provider(), params=params, timeout=self.timeout)
        r.raise_for_status()
        payload = r.json()
        return self._normalize(user_id, payload)
