import pytest


@pytest.mark.xfail(reason="API-side time-window filtering not implemented yet; enable when feature lands", strict=False)
def test_api_time_window_filters_records_server_side(monkeypatch):
    """
    Placeholder: once the API enforces 'from'/'to' server-side, this test should verify
    that records outside the specified window are not returned.

    Suggested approach when ready:
    - Spin up test app/client or mock requests.get to an API that applies filtering.
    - Call adapter.fetch_walk(user_id, from_iso, to_iso) and assert all returned dates
      lie within the [from_iso, to_iso] interval.
    """
    assert False, "Pending API time-window feature"
