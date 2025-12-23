from hdt_mcp.mcp_governor import _shape_for_purpose

def test_shape_for_purpose_analytics_redacts_connector_ids():
    payload = {
        "user_id": 1,
        "kind": "walk",
        "selected_source": "gamebus",
        "attempts": [{"source": "gamebus", "ok": True}],
        "records": [{"steps": 1000}],
        "provenance": {"player_id": "123", "email": "x@y", "token": "secret", "note": "ok"},
    }
    out = _shape_for_purpose(payload, "analytics")
    assert out["purpose"] == "analytics"
    assert out["provenance"] == {"note": "ok"}  # redacted keys removed


def test_shape_for_purpose_coaching_keeps_provenance():
    payload = {
        "user_id": 1,
        "kind": "walk",
        "selected_source": "gamebus",
        "attempts": [{"source": "gamebus", "ok": True}],
        "records": [{"steps": 1000}],
        "provenance": {"player_id": "123", "email": "x@y", "note": "ok"},
    }
    out = _shape_for_purpose(payload, "coaching")
    assert out["purpose"] == "coaching"
    assert out["provenance"]["player_id"] == "123"
    assert out["provenance"]["email"] == "x@y"


def test_shape_for_purpose_modeling_returns_not_supported_error_for_raw():
    payload = {
        "user_id": 1,
        "kind": "walk",
        "tool": "hdt.walk.fetch.v1",
        "records": [{"steps": 1000}],
    }
    out = _shape_for_purpose(payload, "modeling")
    assert "error" in out
    assert out["error"]["code"] == "not_supported"
    assert out["purpose"] == "modeling"
