import inspect
import pytest

import hdt_mcp.mcp_governor as mg


async def _acall(obj, method: str, **kwargs):
    """Call obj.method with only the kwargs it actually accepts (signature-safe)."""
    fn = getattr(obj, method)
    sig = inspect.signature(fn)
    filtered = {k: v for k, v in kwargs.items() if k in sig.parameters}
    return await fn(**filtered)


@pytest.mark.asyncio
async def test_fetch_walk_rejects_bad_prefer_data(monkeypatch):
    # avoid file telemetry writes
    monkeypatch.setattr(mg, "log_event", lambda *a, **k: None)

    gov = mg.HDTGovernor()
    out = await _acall(gov, "fetch_walk", user_id=1, prefer_data="NOPE", purpose="analytics")

    assert isinstance(out, dict)
    assert "error" in out
    assert out["error"]["code"] == "bad_request"


@pytest.mark.asyncio
async def test_fetch_walk_vault_first_hit(monkeypatch):
    monkeypatch.setattr(mg, "log_event", lambda *a, **k: None)

    # Vault enabled and has data
    monkeypatch.setattr(mg.vault_store, "enabled", lambda: True)

    def fake_fetch_walk(**kwargs):
        return {
            "user_id": kwargs["user_id"],
            "kind": "walk",
            "records": [{"date": "2025-01-01", "steps": 123}],
            "provenance": {"note": "from vault"},
        }

    monkeypatch.setattr(mg.vault_store, "fetch_walk", fake_fetch_walk)

    gov = mg.HDTGovernor()

    async def should_not_call(*a, **k):
        raise AssertionError("Sources MCP should not be called on vault-first hit")

    monkeypatch.setattr(gov.sources, "call_tool", should_not_call)

    out = await _acall(
        gov,
        "fetch_walk",
        user_id=1,
        prefer="gamebus",
        prefer_data="auto",
        purpose="analytics",
    )

    assert out.get("user_id") == 1
    assert out.get("kind") in {"walk", "walk.fetch"} or "records" in out
    assert out.get("records")  # must exist
    if "selected_source" in out:
        assert out["selected_source"] == "vault"
    if "attempts" in out:
        assert any(a.get("source") == "vault" for a in out["attempts"])


@pytest.mark.asyncio
async def test_fetch_walk_live_fail_then_auto_fallback_to_vault(monkeypatch):
    monkeypatch.setattr(mg, "log_event", lambda *a, **k: None)
    monkeypatch.setattr(mg.vault_store, "enabled", lambda: True)

    # first vault read = empty, fallback vault read = has records
    calls = {"n": 0}

    def fake_fetch_walk(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"user_id": kwargs["user_id"], "kind": "walk", "records": []}
        return {
            "user_id": kwargs["user_id"],
            "kind": "walk",
            "records": [{"date": "2025-01-02", "steps": 999}],
        }

    monkeypatch.setattr(mg.vault_store, "fetch_walk", fake_fetch_walk)

    gov = mg.HDTGovernor()

    async def fake_call_tool(tool_name, args):
        # both live sources fail
        return {"error": {"code": "upstream_failed", "message": tool_name}}

    monkeypatch.setattr(gov.sources, "call_tool", fake_call_tool)

    out = await _acall(
        gov,
        "fetch_walk",
        user_id=1,
        prefer="gamebus",
        prefer_data="auto",
        purpose="analytics",
    )

    assert out.get("records")  # came from vault fallback
    if "selected_source" in out:
        assert out["selected_source"] == "vault"
    if "attempts" in out:
        assert any(a.get("source") == "vault_fallback" for a in out["attempts"])
