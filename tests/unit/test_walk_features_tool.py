from hdt_mcp.mcp_governor import _walk_features_from_records

def test_walk_features_from_records_basic():
    records = [{"steps": 100}, {"steps": 200}, {"steps": "300"}]
    feats = _walk_features_from_records(records)
    assert feats["days"] == 3
    assert feats["total_steps"] == 600
    assert feats["avg_steps"] == 200
    assert feats["min_steps"] == 100
    assert feats["max_steps"] == 300
