from HDT_MCP.server import _redact_inplace

def test_redact_paths():
    doc = {"user": {"email": "a@b.c"}, "list": [{"user": {"email": "x"}}]}
    _redact_inplace(doc, ["user.email", "list.user.email"])
    assert doc["user"]["email"] == "***redacted***"
    assert doc["list"][0]["user"]["email"] == "***redacted***"
