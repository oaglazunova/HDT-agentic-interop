import copy
import HDT_MCP.server as srv

def test_policy_deny_tool(monkeypatch):
    monkeypatch.setattr(srv, "_POLICY_OVERRIDE", {
        "defaults": {"analytics": {"allow": True, "redact": []}},
        "tools": {
            "hdt.get_walk_data@v1": {
                "analytics": {"allow": False}
            }
        }
    }, raising=False)

    payload = {"ok": True}
    out = srv._apply_policy("analytics", "hdt.get_walk_data@v1", payload, client_id="TEST")
    assert isinstance(out, dict)
    assert out.get("error") == "denied_by_policy"
    assert out.get("tool") == "hdt.get_walk_data@v1"

def test_policy_redact_nested_list(monkeypatch):
    monkeypatch.setattr(srv, "_POLICY_OVERRIDE", {
        "defaults": {
            "analytics": {
                "allow": True,
                "redact": [
                    "streams.walk.records.date",
                    "streams.walk.records.steps"
                ]
            }
        }
    }, raising=False)

    payload = {
        "streams": {
            "walk": {
                "records": [
                    {"date":"2025-11-01","steps":123,"kcalories": 1.2},
                    {"date":"2025-11-02","steps":456}
                ]
            }
        }
    }
    original = copy.deepcopy(payload)

    out = srv._apply_policy("analytics", "vault.integrated@v1", payload, client_id="TEST")
    tok = srv.REDACT_TOKEN

    # list redaction should touch each element
    assert out["streams"]["walk"]["records"][0]["date"] == tok
    assert out["streams"]["walk"]["records"][0]["steps"] == tok
    assert out["streams"]["walk"]["records"][0]["kcalories"] == 1.2  # untouched

    assert out["streams"]["walk"]["records"][1]["date"] == tok
    assert out["streams"]["walk"]["records"][1]["steps"] == tok

    # ensure in-place mutation (documented behavior)
    assert payload is out
