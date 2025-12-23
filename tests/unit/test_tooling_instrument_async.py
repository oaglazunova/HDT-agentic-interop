import pytest

import hdt_common.tooling as tooling
from hdt_common.tooling import InstrumentConfig, PolicyConfig, instrument_async_tool

@pytest.mark.asyncio
async def test_instrument_async_tool_rejects_bad_purpose(monkeypatch):
    # capture telemetry calls without writing files
    events = []

    monkeypatch.setattr(tooling, "log_event", lambda *a, **k: events.append((a, k)))

    cfg = InstrumentConfig(kind="tool", name="hdt.test.v1", client_id="C1", new_corr_id_per_call=True)

    def apply_policy(purpose, tool, payload, client_id):
        return {}

    def apply_policy_safe(purpose, tool, payload, client_id):
        return payload

    def policy_last_meta():
        return {"meta": True}

    pol = PolicyConfig(
        lanes={"analytics", "modeling", "coaching"},
        apply_policy=apply_policy,
        apply_policy_safe=apply_policy_safe,
        policy_last_meta=policy_last_meta,
    )

    @instrument_async_tool(cfg, policy=pol)
    async def fn(user_id: int, purpose: str = "analytics"):
        return {"ok": True}

    out = await fn(user_id=1, purpose="INVALID")
    assert "error" in out
    assert out["error"]["code"] == "bad_request"
    assert events  # logged


@pytest.mark.asyncio
async def test_instrument_async_tool_denies_fast(monkeypatch):
    events = []
    monkeypatch.setattr(tooling, "log_event", lambda *a, **k: events.append((a, k)))

    cfg = InstrumentConfig(kind="tool", name="hdt.walk.fetch.v1", client_id="C1", new_corr_id_per_call=True)

    def apply_policy(purpose, tool, payload, client_id):
        return {"error": {"code": "denied_by_policy", "message": "no"}}

    def apply_policy_safe(purpose, tool, payload, client_id):
        raise AssertionError("apply_policy_safe must not be called on deny-fast")

    def policy_last_meta():
        return {"rule": "deny"}

    pol = PolicyConfig(
        lanes={"analytics", "modeling", "coaching"},
        apply_policy=apply_policy,
        apply_policy_safe=apply_policy_safe,
        policy_last_meta=policy_last_meta,
    )

    @instrument_async_tool(cfg, policy=pol)
    async def fn(user_id: int, purpose: str = "analytics"):
        return {"ok": True}

    out = await fn(user_id=1, purpose="modeling")
    assert out.get("error", {}).get("code") == "denied_by_policy"
    assert events
