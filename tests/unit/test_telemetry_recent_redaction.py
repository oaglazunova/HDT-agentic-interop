import importlib
import json

import hdt_common.telemetry as t

def test_telemetry_recent_redacts_pii_and_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("HDT_TELEMETRY_DIR", str(tmp_path))
    monkeypatch.delenv("HDT_DISABLE_TELEMETRY", raising=False)

    importlib.reload(t)

    p = tmp_path / "mcp-telemetry.jsonl"
    p.write_text(
        json.dumps({
            "ts": "2025-01-01T00:00:00Z",
            "kind": "governor",
            "name": "walk.fetch",
            "args": {
                "args": {"user_id": 1, "email": "x@y", "token": "secret"},
                "purpose": "analytics",
            },
            "ok": True,
            "ms": 1,
        }) + "\n",
        encoding="utf-8",
    )

    out = t.telemetry_recent(n=10)
    rec = out["records"][0]
    inner = rec["args"]["args"]
    assert inner["user_id"] == "***redacted***"
    assert inner["email"] == "***redacted***"
    assert inner["token"] == "***redacted***"
