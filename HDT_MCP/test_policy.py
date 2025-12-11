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
    assert "error" in out and isinstance(out["error"], dict)
    assert out["error"].get("code") == "denied_by_policy"
    assert "denied" in out["error"].get("message", "").lower()
    assert out.get("purpose") == "modeling"
    assert out.get("tool") == "hdt.get_walk_data@v1"
    

def test_policy_tool_twice_uses_unmutated_cache(set_policy, monkeypatch):
    """Call a cached tool twice with different policies.
    First call redacts and caches the payload; second call (no redaction)
    must return the original value, proving the cache was not mutated by policy.
    This guards against the cache-mutation bug where in-place redaction corrupts
    the cached object.
    """
    # Ensure clean cache and deterministic backend
    srv._cache.clear()
    base = {"user": {"email": "pii@demo.io", "name": "Zoe"}, "steps": 111}

    def fake_hdt_get(path, params=None):
        # Return a fresh copy to simulate a backend response
        return copy.deepcopy(base)

    monkeypatch.setattr(srv, "_hdt_get", fake_hdt_get, raising=True)

    # 1) Policy that redacts the email
    set_policy({
        "defaults": {
            "analytics": {"allow": True, "redact": ["user.email"]}
        }
    })
    out1 = srv.tool_get_sugarvita_data("101")
    assert isinstance(out1, dict)
    assert out1["user"]["email"] == srv.REDACT_TOKEN

    # 2) Change policy to no redaction and force policy cache reload
    set_policy({
        "defaults": {
            "analytics": {"allow": True, "redact": []}
        }
    })
    srv._policy_reset_cache()

    # Call again; should hit the response cache but with original (non-redacted) values
    out2 = srv.tool_get_sugarvita_data("101")
    assert out2["user"]["email"] == base["user"]["email"], "Second call should not return a doubly-redacted cached value"
    assert out2["user"]["name"] == base["user"]["name"]
    assert out2["steps"] == base["steps"]
