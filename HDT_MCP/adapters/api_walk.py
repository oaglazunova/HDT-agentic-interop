from __future__ import annotations
from typing import Callable, List
import requests
from ..domain.models import WalkRecord
from ..domain.ports import WalkSourcePort
from ..models.behavior import _headers as _default_headers


class ApiWalkAdapter(WalkSourcePort):
    """
    Wraps your Flask API (/get_walk_data?user_id=..).
    """

    def __init__(self,
                 base_url: str,
                 headers_provider: Callable[[], dict] | None = _default_headers,
                 timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.headers_provider = headers_provider or (lambda: {})
        self.timeout = timeout

    def _url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    def fetch_walk(self, user_id: int) -> List[WalkRecord]:
        r = requests.get(
            self._url("/get_walk_data"),
            params={"user_id": user_id},
            headers=self.headers_provider(),
            timeout=self.timeout
        )
        r.raise_for_status()
        data = r.json()

        # Normalize: endpoint may return [{"user_id":..,"data":[...]}, ...] or {"user_id":..,"data":[...]}
        records = []
        if isinstance(data, list):
            leaf = next((x for x in data if str(x.get("user_id")) == str(user_id)), None)
            records = (leaf or {}).get("data", []) or (leaf or {}).get("records", [])
        elif isinstance(data, dict):
            records = data.get("data", []) or data.get("records", []) or []

        return [WalkRecord.model_validate(r) for r in records]
