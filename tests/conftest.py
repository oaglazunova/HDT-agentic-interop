from __future__ import annotations

import pytest_asyncio

from tests.helpers.mcp_runtime import build_test_env, mcp_stdio_session


@pytest_asyncio.fixture
async def gateway_session(tmp_path):
    """Initialized session for the HDT gateway MCP server (stdio transport)."""
    env = build_test_env(tmp_path)
    async with mcp_stdio_session("hdt_mcp.gateway", env=env) as session:
        yield session


@pytest_asyncio.fixture
async def sources_session(tmp_path):
    """Initialized session for the Sources MCP server (stdio transport)."""
    env = build_test_env(tmp_path)
    async with mcp_stdio_session("hdt_sources_mcp.server", env=env) as session:
        yield session
