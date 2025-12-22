"""Shared runtime helpers for MCP integration tests.

Why this exists:
- Integration tests spawn MCP servers as subprocesses (stdio transport) and connect via MCP ClientSession.
- Without a shared harness, each test tends to re-implement the same boilerplate (env setup, session init,
  result unwrapping), which drifts over time.

Design goals:
- Keep unit tests hermetic: importing this module must not require MCP to be installed.
- Make result parsing resilient to common MCP/FastMCP response shapes.
"""

from __future__ import annotations

import json
import os
import asyncio
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, AsyncIterator, Iterable, Mapping

import pytest

# IMPORTANT:
# Do not import-or-skip MCP at module import time; otherwise unit tests will be skipped
# if the optional 'mcp' dependency is not installed.
_MCP_IMPORT_ERROR: Exception | None = None
try:
    from mcp import ClientSession  # type: ignore
    from mcp.client.stdio import StdioServerParameters, stdio_client  # type: ignore
except Exception as e:  # pragma: no cover
    _MCP_IMPORT_ERROR = e
    ClientSession = Any  # type: ignore[misc,assignment]
    StdioServerParameters = Any  # type: ignore[misc,assignment]
    stdio_client = None  # type: ignore[assignment]

if TYPE_CHECKING:  # pragma: no cover
    from mcp import ClientSession as ClientSessionT  # noqa: F401


def _require_mcp() -> None:
    if _MCP_IMPORT_ERROR is not None:
        pytest.skip(
            f"MCP is not available in this environment ({_MCP_IMPORT_ERROR!r}). "
            "Install test dependencies (e.g., pip install -e '.[dev]')."
        )


def build_test_env(tmp_path: Path, *, transport: str = "stdio", extra: Mapping[str, str] | None = None) -> dict[str, str]:
    """Build a clean environment for integration tests.

    - Starts from current process env (so PATH, python, etc. stay intact).
    - Forces MCP transport to stdio by default.
    - Redirects telemetry output to a temp folder to avoid polluting the repo and to keep tests isolated.
    """
    env = dict(os.environ)
    env["MCP_TRANSPORT"] = transport

    # Keep integration test runs isolated and prevent accidental commits of telemetry/log artefacts.
    env.setdefault("HDT_TELEMETRY_DIR", str(Path(tmp_path) / "telemetry"))

    if extra:
        for k, v in extra.items():
            env[str(k)] = str(v)

    return env


@asynccontextmanager
async def mcp_stdio_session(
    module: str,
    *,
    env: Mapping[str, str] | None = None,
    python_executable: str = sys.executable,
) -> AsyncIterator[ClientSession]:
    """Start an MCP server (`python -m <module>`) over stdio and yield an initialized ClientSession."""
    _require_mcp()
    assert stdio_client is not None  # for type checkers

    server = StdioServerParameters(
        command=python_executable,
        args=["-m", module],
        env=dict(env) if env is not None else dict(os.environ),
    )

    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await asyncio.wait_for(session.initialize(), timeout=30)
            yield session


async def list_tool_names(session: ClientSession) -> list[str]:
    tools = await session.list_tools()
    return [t.name for t in tools.tools]


def unwrap_json_result(res: Any) -> dict[str, Any]:
    """Parse common MCP call_tool result shapes into a Python dict."""
    if isinstance(res, dict):
        return res

    content = getattr(res, "content", None)
    if isinstance(content, list) and content:
        c0 = content[0]

        # Some implementations return a dict with a JSON payload directly.
        if isinstance(c0, dict):
            if "json" in c0 and isinstance(c0["json"], dict):
                return c0["json"]
            if "text" in c0 and isinstance(c0["text"], str):
                return json.loads(c0["text"])

        # FastMCP TextContent object: .text is a string
        text = getattr(c0, "text", None)
        if isinstance(text, str):
            return json.loads(text)

    # Last-resort: some wrappers expose a 'json' attribute
    j = getattr(res, "json", None)
    if isinstance(j, dict):
        return j

    raise AssertionError(f"Unexpected tool result shape: {type(res)} {res!r}")


async def call_tool_json(session: ClientSession, tool_name: str, args: Mapping[str, Any] | None = None) -> dict[str, Any]:
    res = await asyncio.wait_for(session.call_tool(tool_name, dict(args or {})), timeout=30)
    return unwrap_json_result(res)


async def assert_tools_present(session: ClientSession, expected: Iterable[str]) -> None:
    names = await list_tool_names(session)
    missing = [t for t in expected if t not in names]
    assert not missing, f"Missing tools: {missing}. Present tools: {sorted(names)}"
