from __future__ import annotations

import pytest

from tests.helpers.mcp_runtime import assert_tools_present, call_tool_json


@pytest.mark.integration
@pytest.mark.asyncio
async def test_hdt_mcp_gateway_healthz_and_tools(gateway_session):
    await assert_tools_present(gateway_session, ["hdt.healthz.v1", "hdt.walk.fetch.v1"])

    payload = await call_tool_json(gateway_session, "hdt.healthz.v1", {})
    assert payload.get("ok") is True
