import pytest

@pytest.mark.asyncio
async def test_gateway_denies_modeling_on_raw_fetch(monkeypatch):
    """
    modeling + hdt.walk.fetch.v1 must be denied before calling the governor.
    """
    import hdt_mcp.gateway as gw

    called = {"n": 0}

    async def _should_not_be_called(**kwargs):
        called["n"] += 1
        return {"user_id": kwargs.get("user_id"), "kind": "walk", "records": []}

    monkeypatch.setattr(gw.gov, "fetch_walk", _should_not_be_called)

    out = await gw.hdt_walk_fetch(user_id=1, purpose="modeling")

    assert called["n"] == 0
    assert isinstance(out, dict)
    assert "error" in out
    assert out["error"].get("code") in {"denied_by_policy", "denied"}  # depending on your typed_error naming


@pytest.mark.asyncio
async def test_gateway_allows_analytics_and_calls_governor(monkeypatch):
    """
    analytics + hdt.walk.fetch.v1 must call the governor and return its payload (post policy-safe step).
    """
    import hdt_mcp.gateway as gw

    called = {"n": 0}

    async def _fake_fetch_walk(**kwargs):
        called["n"] += 1
        return {
            "user_id": kwargs["user_id"],
            "kind": "walk",
            "selected_source": "gamebus",
            "attempts": [{"source": "gamebus", "ok": True}],
            "records": [{"date": "2025-11-03", "steps": 123}],
            "provenance": {"player_id": "123", "email": "x@y", "note": "ok"},
        }

    monkeypatch.setattr(gw.gov, "fetch_walk", _fake_fetch_walk)

    out = await gw.hdt_walk_fetch(user_id=1, purpose="analytics")

    assert called["n"] == 1
    assert out.get("user_id") == 1
    assert out.get("kind") == "walk"
    # Redaction/minimization is handled in governor shaping + policy-safe.
    # If you want a strict assertion, keep it in the purpose-shaping unit tests below.


@pytest.mark.asyncio
async def test_gateway_allows_modeling_on_features_tool(monkeypatch):
    """
    modeling + hdt.walk.features.v1 must be allowed (and should not expose raw records).
    """
    import hdt_mcp.gateway as gw

    called = {"n": 0}

    async def _fake_walk_features(**kwargs):
        called["n"] += 1
        return {
            "user_id": kwargs["user_id"],
            "kind": "walk_features",
            "features": {"steps_sum": 1000},
            # If your contract forbids 'records' for modeling, your real implementation should not return it.
        }

    monkeypatch.setattr(gw.gov, "walk_features", _fake_walk_features)

    out = await gw.hdt_walk_features(user_id=1, purpose="modeling")

    assert called["n"] == 1
    assert "error" not in out
    assert out.get("kind") == "walk_features"
