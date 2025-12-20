from hdt_mcp.policy.engine import apply_policy


def test_policy_denies_modeling_for_raw_walk_fetch():
    out = apply_policy("modeling", "hdt.walk.fetch@v1", {}, client_id="MODEL_DEVELOPER_1")
    assert isinstance(out, dict)
    assert "error" in out
    assert out["error"]["code"] == "denied_by_policy"


def test_policy_allows_analytics_for_raw_walk_fetch():
    out = apply_policy("analytics", "hdt.walk.fetch@v1", {}, client_id="MODEL_DEVELOPER_1")
    assert isinstance(out, dict)
    assert "error" not in out
