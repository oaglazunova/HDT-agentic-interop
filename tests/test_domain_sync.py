from HDT_MCP.domain.services import sync_user_walk

def test_sync_placeholder_walk():
    recs = sync_user_walk("Placeholder Walk", "demo", None)
    assert isinstance(recs, list)
    assert all("date" in r and "steps" in r for r in recs)
