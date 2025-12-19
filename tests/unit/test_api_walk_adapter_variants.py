from __future__ import annotations
from typing import Any

from hdt_mcp.adapters.api_walk import ApiWalkAdapter


class _FakeResp:
    def __init__(self, payload: Any, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise AssertionError("bad status")

    def json(self):
        return self._payload


def test_list_payload_picks_matching_user_and_normalizes(monkeypatch):
    def fake_get(url, params=None, headers=None, timeout=None):
        # Return a list of envelopes with different user ids
        return _FakeResp([
            {"user_id": 111, "data": [{"date": "2025-10-01", "steps": 1}]},
            {"user_id": 222, "records": [
                {"date": "2025-10-02", "steps": 2, "kcalories": 3.5},
                {"date": "2025-10-03", "steps": 4},
            ]},
        ])

    monkeypatch.setattr("requests.get", fake_get, raising=True)

    # Use legacy timeout_sec to exercise that code path
    adapter = ApiWalkAdapter(base_url="http://x", headers_provider=lambda: {}, timeout_sec=7)
    out = adapter.fetch_walk(222)
    assert len(out) == 2
    assert out[0].steps == 2 and out[0].kcalories == 3.5
    assert out[1].steps == 4


def test_unknown_payload_shape_returns_empty(monkeypatch):
    def fake_get(url, params=None, headers=None, timeout=None):
        class Weird:
            pass
        return _FakeResp(Weird())

    monkeypatch.setattr("requests.get", fake_get, raising=True)
    adapter = ApiWalkAdapter(base_url="http://x")
    out = adapter.fetch_walk(1)
    assert out == []
