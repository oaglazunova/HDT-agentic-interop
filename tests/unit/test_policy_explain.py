from hdt_mcp.policy.engine import explain_policy

def test_policy_explain_denies_modeling_for_raw_walk_fetch():
    out = explain_policy("modeling", "hdt.walk.fetch@v1", client_id="MODEL_DEVELOPER_1")
    assert out["resolved"]["allow"] is False

def test_policy_explain_allows_modeling_for_walk_features():
    out = explain_policy("modeling", "hdt.walk.features@v1", client_id="MODEL_DEVELOPER_1")
    assert out["resolved"]["allow"] is True
