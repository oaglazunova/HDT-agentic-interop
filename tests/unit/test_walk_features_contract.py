import pytest
from hdt_mcp.mcp_governor import HDTGovernor

@pytest.mark.asyncio
async def test_walk_features_returns_no_raw_records_and_is_modeling_safe(monkeypatch):
    gov = HDTGovernor()

    async def fake_fetch_walk(*args, **kwargs):
        # This simulates the *rich* (coaching) payload the governor would use internally.
        return {
            "user_id": 1,
            "kind": "walk",
            "selected_source": "gamebus",
            "attempts": [{"source": "gamebus", "ok": True}],
            "records": [{"steps": 100}, {"steps": 200}],
            "provenance": {"player_id": "123", "email": "x@y", "note": "ok"},
        }

    monkeypatch.setattr(gov, "fetch_walk", fake_fetch_walk)

    out = await gov.walk_features(user_id=1, purpose="modeling")

    assert isinstance(out, dict)
    assert "error" not in out
    assert out.get("kind") == "walk_features"
    assert "features" in out

    # Critical: do not return raw records in a modeling-safe tool
    assert "records" not in out

    # Provenance should be minimal (no connector identifiers)
    prov = out.get("provenance") or {}
    assert isinstance(prov, dict)
    assert "player_id" not in prov
    assert "email" not in prov


@pytest.mark.asyncio
async def test_walk_features_rejects_non_modeling_purpose(monkeypatch):
    gov = HDTGovernor()

    async def fake_fetch_walk(*args, **kwargs):
        return {
            "user_id": 1,
            "kind": "walk",
            "selected_source": "gamebus",
            "attempts": [],
            "records": [{"steps": 100}],
        }

    monkeypatch.setattr(gov, "fetch_walk", fake_fetch_walk)

    out = await gov.walk_features(user_id=1, purpose="analytics")
    assert "error" in out
    assert out["error"]["code"] == "bad_request"
