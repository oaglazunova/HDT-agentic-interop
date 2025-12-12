from HDT_MCP.server import hdt_walk_stream

def test_walk_tool_aggregate_smoke():
    # Use the existing MCP tool that exposes the walk stream
    out = hdt_walk_stream(user_id=1)
    assert isinstance(out, dict)
    # Expect the domain-shaped payload with records and stats
    assert "records" in out
    assert isinstance(out["records"], list)
