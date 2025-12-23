from __future__ import annotations

import pytest

from tests.helpers.mcp_runtime import assert_tools_present, call_tool_json


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sources_mcp_healthz_and_tools(sources_session):
    await assert_tools_present(sources_session, ["healthz.v1", "sources.status.v1"])

    payload = await call_tool_json(sources_session, "healthz.v1", {})
    assert payload.get("ok") is True
