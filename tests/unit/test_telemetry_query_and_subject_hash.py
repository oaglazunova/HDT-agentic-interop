import hashlib
import importlib
import json

import hdt_common.telemetry as t


def test_telemetry_subject_hash_and_query_filters(tmp_path, monkeypatch):
    # Configure telemetry module to write into a temporary dir
    monkeypatch.setenv("HDT_TELEMETRY_DIR", str(tmp_path))
    monkeypatch.setenv("HDT_TELEMETRY_SUBJECT_SALT", "demo-salt")
    monkeypatch.delenv("HDT_DISABLE_TELEMETRY", raising=False)

    importlib.reload(t)

    # Write a denied event through log_event (so subject_hash is computed pre-redaction)
    t.log_event(
        kind="tool",
        name="hdt.walk.fetch.v1",
        args={
            "args": {"user_id": 1, "email": "x@y", "token": "secret"},
            "purpose": "coaching",
            "error": {"code": "denied_by_policy"},
        },
        ok=False,
        ms=12,
        client_id="COACHING_AGENT",
        corr_id="corr-1",
    )

    # Validate raw record persisted with redaction + subject_hash
    p = tmp_path / "mcp-telemetry.jsonl"
    raw = p.read_text(encoding="utf-8").splitlines()[0]
    rec = json.loads(raw)

    expected = hashlib.sha256(b"demo-salt:1").hexdigest()[:16]
    assert rec.get("subject_hash") == expected

    inner = rec["args"]["args"]
    assert inner["user_id"] == "***redacted***"
    assert inner["email"] == "***redacted***"
    assert inner["token"] == "***redacted***"

    out = t.telemetry_query(
        n=10,
        client_id="COACHING_AGENT",
        purpose="coaching",
        ok=False,
        error_code="denied_by_policy",
    )

    assert isinstance(out, dict)
    assert len(out.get("records") or []) == 1
    assert out["records"][0].get("subject_hash") == expected
