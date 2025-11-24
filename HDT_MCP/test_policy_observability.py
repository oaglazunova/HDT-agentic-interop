import pytest
from HDT_MCP import server as srv

@pytest.fixture(autouse=True)
def reset_policy_cache(monkeypatch):
    # Ensure a clean slate per test
    monkeypatch.setattr(srv, "_POLICY_OVERRIDE", None, raising=False)
    try:
        srv._policy_reset_cache()
    except Exception:
        pass
    yield
    # cleanup
    monkeypatch.setattr(srv, "_POLICY_OVERRIDE", None, raising=False)
    try:
        srv._policy_reset_cache()
    except Exception:
        pass

def test_policy_tool_deny_sets_meta(monkeypatch):
    # Tool-level deny on modeling lane
    monkeypatch.setattr(
        srv, "_POLICY_OVERRIDE",
        {"tools": {"hdt.get_walk_data@v1": {"modeling": {"allow": False}}}}
    )
    payload = {"user": {"email": "pii@demo.io"}}
    out = srv._apply_policy("modeling", "hdt.get_walk_data@v1", payload)

    # Denied + payload must remain unchanged
    assert isinstance(out, dict) and out.get("error") == "denied_by_policy"
    assert payload["user"]["email"] == "pii@demo.io"

    meta = srv._policy_last_meta()
    assert meta["allowed"] is False
    assert meta["redactions"] == 0
    assert meta["purpose"] == "modeling"
    assert meta["tool"] == "hdt.get_walk_data@v1"

def test_policy_nested_redaction_list(monkeypatch):
    # Defaults redact users.email (list-of-objects)
    monkeypatch.setattr(
        srv, "_POLICY_OVERRIDE",
        {"defaults": {"analytics": {"allow": True, "redact": ["users.email"]}}}
    )

    payload = {
        "users": [
            {"email": "a@x", "name": "A"},
            {"email": "b@x", "name": "B"},
        ],
        "note": "ok"
    }
    srv._apply_policy("analytics", "any.tool@v1", payload)

    # Both emails redacted
    assert payload["users"][0]["email"] == srv.REDACT_TOKEN
    assert payload["users"][1]["email"] == srv.REDACT_TOKEN

    meta = srv._policy_last_meta()
    assert meta["allowed"] is True
    assert meta["redactions"] == 2  # one per email field
