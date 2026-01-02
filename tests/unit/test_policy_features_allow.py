from hdt_mcp.policy.engine import apply_policy

def test_policy_allows_modeling_for_walk_features():
    out = apply_policy("modeling", "hdt.walk.features.v1", {}, client_id="MODEL_DEVELOPER_1")
    assert isinstance(out, dict)
    assert "error" not in out
