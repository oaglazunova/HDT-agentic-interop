from __future__ import annotations
from typing import Any, Dict

from HDT_MCP.adapters.api_walk import ApiWalkAdapter


class _FakeResp:
    def __init__(self, payload: Any, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise AssertionError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def test_api_walk_adapter_passes_time_window_params(monkeypatch):
    captured: Dict[str, Any] = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        captured["url"] = url
        captured["params"] = dict(params or {})
        captured["headers"] = dict(headers or {})
        captured["timeout"] = timeout
        # Return dict shape with records
        return _FakeResp({
            "user_id": 123,
            "records": [
                {"date": "2025-11-01", "steps": 10},
                {"date": "2025-11-02", "steps": 20},
            ],
        })

    monkeypatch.setattr("requests.get", fake_get, raising=True)

    hdrs = {"X-Auth": "token"}
    adapter = ApiWalkAdapter(base_url="http://api.example", headers_provider=lambda: hdrs, timeout=15)

    recs = adapter.fetch_walk(
        123,
        from_iso="2025-11-01",
        to_iso="2025-11-10",
        limit=50,
        offset=5,
    )

    assert captured["url"].endswith("/get_walk_data")
    assert captured["headers"] == hdrs
    assert captured["timeout"] == 15

    params = captured["params"]
    assert params["user_id"] == 123
    assert params["from"] == "2025-11-01"
    assert params["to"] == "2025-11-10"
    assert params["limit"] == 50
    assert params["offset"] == 5

    # Records converted to WalkRecord
    assert len(recs) == 2
    assert recs[0].steps == 10 and recs[0].date == "2025-11-01"
    assert recs[1].steps == 20 and recs[1].date == "2025-11-02"
