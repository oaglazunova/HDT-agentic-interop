import importlib
import json

import pytest


def _write_record(path, rec):
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


@pytest.mark.asyncio
async def test_gateway_telemetry_query_tool_filters(tmp_path, monkeypatch):
    # Disable telemetry so calling the tool does not pollute the file
    monkeypatch.setenv("HDT_DISABLE_TELEMETRY", "1")
    monkeypatch.setenv("HDT_TELEMETRY_DIR", str(tmp_path))

    # Ensure modules rebind env-configured telemetry dir and disable flag
    import hdt_common.telemetry as telem
    importlib.reload(telem)
    import hdt_common.tooling as tooling
    importlib.reload(tooling)
    import hdt_mcp.gateway as gw
    importlib.reload(gw)

    p = tmp_path / "mcp-telemetry.jsonl"

    # A matching denied record
    _write_record(
        p,
        {
            "ts": "2026-01-10T00:00:00Z",
            "kind": "tool",
            "name": "hdt.walk.fetch.v1",
            "client_id": "COACHING_AGENT",
            "request_id": "r1",
            "corr_id": "c1",
            "args": {"purpose": "coaching", "error": {"code": "denied_by_policy"}},
            "ok": False,
            "ms": 1,
            "subject_hash": "abcd",
        },
    )

    # A non-matching record
    _write_record(
        p,
        {
            "ts": "2026-01-10T00:00:01Z",
            "kind": "tool",
            "name": "hdt.walk.fetch.v1",
            "client_id": "OTHER",
            "request_id": "r2",
            "corr_id": "c2",
            "args": {"purpose": "coaching", "error": {"code": "denied_by_policy"}},
            "ok": False,
            "ms": 1,
            "subject_hash": "zzzz",
        },
    )

    out = await gw.hdt_telemetry_query(
        n=10,
        lookback_s=999999999,
        client_id="COACHING_AGENT",
        event_purpose="coaching",
        ok=False,
        error_code="denied_by_policy",
        purpose="analytics",
    )

    assert isinstance(out, dict)
    recs = out.get("records") or []
    assert len(recs) == 1
    assert recs[0]["client_id"] == "COACHING_AGENT"
    assert recs[0]["corr_id"] == "c1"
