# HDT_MCP/test_policy.py
import json
import copy
import pytest

from HDT_MCP import server as srv  # import the module to monkeypatch internals
from HDT_MCP.server import _redact_inplace

def test_redact_paths():
    doc = {"user": {"email": "a@b.c"}, "list": [{"user": {"email": "x"}}]}
    _redact_inplace(doc, ["user.email", "list.user.email"])
    assert doc["user"]["email"] == "***redacted***"
    assert doc["list"][0]["user"]["email"] == "***redacted***"

@pytest.fixture
def set_policy(tmp_path, monkeypatch):
    """Helper to inject a temporary policy.json and force policy tools ON."""
    def _apply(policy_dict: dict):
        path = tmp_path / "policy.json"
        path.write_text(json.dumps(policy_dict), encoding="utf-8")
        # Point server to our temp policy and enable the gate
        monkeypatch.setattr(srv, "_POLICY_PATH", path, raising=True)
        monkeypatch.setattr(srv, "_ENABLE_POLICY", True, raising=True)
        return path
    return _apply

@pytest.mark.skipif(
    not hasattr(srv, "_apply_policy") or not hasattr(srv, "policy_evaluate"),
    reason="server._apply_policy / server.policy_evaluate not present yet",
)
def test_policy_coaching_allows_no_redact(set_policy):
    # Defaults: coaching allows, no redaction
    set_policy({
        "defaults": {
            "coaching": {"allow": True, "redact": []}
        }
    })
    payload = {"user": {"email": "coach@demo.io", "name": "Ada"}, "steps": 1234}
    before = copy.deepcopy(payload)
    after = srv._apply_policy("coaching", "hdt.get_walk_data@v1", payload)
    # Should allow and not redact
    assert after == before
    # And raw policy_evaluate should confirm
    decision = srv.policy_evaluate("coaching")
    assert decision["allow"] is True
    assert decision.get("redact", []) == []

@pytest.mark.skipif(
    not hasattr(srv, "_apply_policy") or not hasattr(srv, "policy_evaluate"),
    reason="server._apply_policy / server.policy_evaluate not present yet",
)
def test_policy_analytics_redacts_email(set_policy):
    # Analytics: redact user.email
    set_policy({
        "defaults": {
            "analytics": {"allow": True, "redact": ["user.email"]}
        }
    })
    payload = {"user": {"email": "pii@demo.io", "name": "Grace"}, "steps": 4321}
    srv._apply_policy("analytics", "hdt.get_walk_data@v1", payload)
    assert payload["user"]["email"] == "***redacted***"  # redacted
    assert payload["user"]["name"] == "Grace"            # untouched
    assert payload["steps"] == 4321                      # untouched

@pytest.mark.skipif(
    not hasattr(srv, "_apply_policy") or not hasattr(srv, "policy_evaluate"),
    reason="server._apply_policy / server.policy_evaluate not present yet",
)
def test_policy_modeling_denies_for_tool(set_policy):
    # Tool-level deny for modeling
    set_policy({
        "tools": {
            "hdt.get_walk_data@v1": {
                "modeling": {"allow": False}
            }
        }
    })
    payload = {"user": {"email": "x@y.z"}, "steps": 10}
    out = srv._apply_policy("modeling", "hdt.get_walk_data@v1", payload)
    assert isinstance(out, dict)
    assert "error" in out
    assert "denied" in out["error"].lower()
    assert out.get("purpose") == "modeling"
    assert out.get("tool") == "hdt.get_walk_data@v1"
