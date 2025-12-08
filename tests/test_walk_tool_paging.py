from HDT_MCP.server import tool_get_walk_data

def test_walk_tool_aggregate_smoke():
    out = tool_get_walk_data(user_id="1", aggregate=True, page_limit=50, max_pages=2)
    assert isinstance(out, dict)
    assert "data" in out
