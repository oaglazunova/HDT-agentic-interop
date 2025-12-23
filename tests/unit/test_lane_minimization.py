from hdt_mcp.mcp_governor import _shape_for_purpose


def test_analytics_minimizes_provenance_identifiers():
    payload = {
        "user_id": 1,
        "kind": "walk",
        "selected_source": "gamebus",
        "records": [{"steps": 1000}],
        "provenance": {"player_id": "123", "email": "x@y", "note": "ok"},
        "attempts": [],
    }
    out = _shape_for_purpose(payload, "analytics")
    assert out["provenance"].get("note") == "ok"
    assert "player_id" not in out["provenance"]
    assert "email" not in out["provenance"]


def test_coaching_keeps_provenance_identifiers():
    payload = {
        "user_id": 1,
        "kind": "walk",
        "selected_source": "gamebus",
        "records": [{"steps": 1000}],
        "provenance": {"player_id": "123", "email": "x@y"},
        "attempts": [],
    }
    out = _shape_for_purpose(payload, "coaching")
    assert out["provenance"]["player_id"] == "123"
    assert out["provenance"]["email"] == "x@y"


def test_modeling_returns_not_supported_error():
    payload = {
        "user_id": 1,
        "kind": "walk",
        "selected_source": "gamebus",
        "records": [{"steps": 1000}],
        "provenance": {"player_id": "123"},
        "attempts": [],
    }
    out = _shape_for_purpose(payload, "modeling")
    assert "error" in out
    assert out["error"]["code"] == "not_supported"
