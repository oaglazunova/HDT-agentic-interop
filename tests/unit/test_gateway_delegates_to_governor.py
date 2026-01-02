import pytest


@pytest.mark.asyncio
async def test_hdt_walk_fetch_delegates_and_filters_args(monkeypatch):
    import hdt_mcp.gateway as gw

    called = {}

    class FakeGov:
        # No **kwargs on purpose: this forces the "filter to allowed params" branch
        async def fetch_walk(self, user_id: int, prefer_data: str = "auto"):
            called["fetch_walk"] = {"user_id": user_id, "prefer_data": prefer_data}
            return {"ok": True, "source": "fake", "records": []}

    monkeypatch.setattr(gw, "gov", FakeGov())

    out = await gw.hdt_walk_fetch(
        user_id=1,
        prefer_data="vault",
        purpose="analytics",     # should be filtered out
        start_date="2025-01-01", # should be filtered out
        end_date="2025-01-31",   # should be filtered out
    )

    assert isinstance(out, dict)
    assert out["ok"] is True
    assert called["fetch_walk"] == {"user_id": 1, "prefer_data": "vault"}


@pytest.mark.asyncio
async def test_hdt_sources_status_delegates_and_filters_args(monkeypatch):
    import hdt_mcp.gateway as gw

    called = {}

    class FakeGov:
        async def sources_status(self, user_id: int):
            called["sources_status"] = {"user_id": user_id}
            return {"ok": True, "sources": {"fake": {"ok": True}}}

    monkeypatch.setattr(gw, "gov", FakeGov())

    out = await gw.hdt_sources_status(user_id=7, purpose="coaching")  # should be filtered out
    assert isinstance(out, dict)
    assert out["ok"] is True
    assert called["sources_status"] == {"user_id": 7}


@pytest.mark.asyncio
async def test_hdt_trivia_fetch_delegates_with_varkw(monkeypatch):
    import hdt_mcp.gateway as gw

    called = {}

    class FakeGov:
        async def fetch_trivia(self, **kwargs):
            called["fetch_trivia"] = kwargs
            return {"ok": True, "source": "fake", "items": []}

    monkeypatch.setattr(gw, "gov", FakeGov())

    out = await gw.hdt_trivia_fetch(
        user_id=3,
        start_date="2025-01-01",
        end_date="2025-01-31",
        purpose="analytics",
    )

    assert isinstance(out, dict)
    assert out["ok"] is True

    # With **kwargs, the delegate passes all bound tool args (including purpose)
    assert called["fetch_trivia"]["user_id"] == 3
    assert called["fetch_trivia"]["start_date"] == "2025-01-01"
    assert called["fetch_trivia"]["end_date"] == "2025-01-31"
    assert called["fetch_trivia"]["purpose"] == "analytics"
