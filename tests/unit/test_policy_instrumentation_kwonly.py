import pytest

from hdt_common.tooling import InstrumentConfig, PolicyConfig, instrument_async_tool
from hdt_mcp.policy import engine as policy_engine


@pytest.mark.asyncio
async def test_instrument_async_tool_passes_client_id_as_keyword():
    cfg = InstrumentConfig(kind="tool", name="hdt.walk.fetch@v1", client_id="MODEL_DEVELOPER_1", attach_corr_id=False)

    pol = PolicyConfig(
        lanes={"analytics", "coaching", "modeling"},
        apply_policy=policy_engine.apply_policy,
        apply_policy_safe=policy_engine.apply_policy_safe,
        policy_last_meta=policy_engine.policy_last_meta,
        purpose_param="purpose",
    )

    @instrument_async_tool(cfg, policy=pol)
    async def dummy(*, purpose: str = "analytics") -> dict:
        return {"ok": True}

    out = await dummy(purpose="analytics")
    assert out["ok"] is True
