from __future__ import annotations
from typing import Optional, List, Callable, Dict, Any
import requests

from hdt_mcp.domain.models import WalkRecord
from hdt_mcp.domain.ports import WalkSourcePort


class ApiWalkAdapter(WalkSourcePort):
    """
    Calls your Flask API (/get_walk_data?user_id=...) and normalizes envelopes
    into List[WalkRecord] for the domain layer.
    """

    def __init__(
        self,
        base_url: str,
        headers_provider: Optional[Callable[[], Dict[str, str]]] = None,
        timeout_sec: Optional[int] = None,
        timeout: Optional[int] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.headers_provider = headers_provider or (lambda: {})
        # Support both legacy 'timeout_sec' and new 'timeout' kwarg.
        # Prefer 'timeout' if provided; fall back to 'timeout_sec'; default 30.
        chosen_timeout = timeout if timeout is not None else (timeout_sec if timeout_sec is not None else 30)
        self.timeout = int(chosen_timeout)

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
        params = {"user_id": user_id}
        if from_iso:
            params["from"] = from_iso
        if to_iso:
            params["to"] = to_iso
        if limit is not None:
            params["limit"] = limit
        if offset is not None:
            params["offset"] = offset

        url = f"{self.base_url}/get_walk_data"
        try:
            r = requests.get(
                url,
                headers=self.headers_provider(),
                params=params,
                timeout=self.timeout,
            )
            # Gracefully degrade on unauthorized in dev/test (no API key)
            if r.status_code in (401, 403):
                return []
            r.raise_for_status()
            payload = r.json()
            return self._normalize(user_id, payload)
        except requests.exceptions.RequestException:
            # Network errors, timeouts, DNS resolution, etc. → return empty
            return []
