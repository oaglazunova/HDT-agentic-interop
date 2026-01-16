from __future__ import annotations

"""Client helper for calling the internal Sources MCP server.

Why this exists
--------------
The HDT MCP gateway (Option D) delegates to an internal "Sources MCP" server
over stdio.

Important implementation note
-----------------------------
The upstream `mcp.client.stdio.stdio_client(...)` context manager is built on
AnyIO cancel scopes. Keeping a *single* stdio_client open and reusing it across
multiple concurrently-scheduled request tasks (as a long-lived singleton) can
cause hard-to-debug hangs and shutdown errors such as:

  "Attempted to exit cancel scope in a different task than it was entered in"

For CI reliability and predictable behavior in an async server, this client
opens a short-lived stdio session per call.
"""

import asyncio
import os
import sys
from typing import Any, Dict

from hdt_config.settings import repo_root
from hdt_common.context import get_request_id, new_request_id


class SourcesMCPClient:
    """Stdio MCP client for the internal Sources MCP server.

    Design choice: **per-call** stdio session.

    This is intentionally conservative: it trades a small startup overhead for
    correctness and avoids AnyIO cancel-scope cross-task issues in CI and
    in server shutdown.
    """

    def __init__(self) -> None:
        # Use the active interpreter (venv-safe). Override via MCP_SOURCES_PYTHON.
        self._command = os.getenv("MCP_SOURCES_PYTHON") or sys.executable
        self._args = ["-m", "hdt_sources_mcp.server"]

        # Put Sources telemetry in its own directory to avoid contention and to
        # keep artifacts tidy.
        root = repo_root()
        self._sources_telemetry_dir = str((root / "artifacts" / "telemetry" / "sources_mcp").resolve())

        # Serialize calls to avoid spawning multiple Sources processes at once.
        self._io_lock = asyncio.Lock()

    def _server_params(self):
        # Lazy import to keep module import-time side effects minimal.
        from mcp.client.stdio import StdioServerParameters

        corr_id = get_request_id() or new_request_id()

        env = dict(os.environ)
        env["MCP_TRANSPORT"] = "stdio"
        env["HDT_TELEMETRY_DIR"] = self._sources_telemetry_dir
        env["HDT_CORR_ID"] = corr_id

        return StdioServerParameters(command=self._command, args=self._args, env=env)

    @staticmethod
    def _unwrap_result(res: Any) -> Any:
        """Unwrap MCP ToolResult to a Python object (best-effort)."""
        content = getattr(res, "content", None)
        if not content:
            return res

        c0 = content[0]
        if isinstance(c0, dict) and "text" in c0:
            return c0["text"]
        return getattr(c0, "text", c0)

    async def call_tool(self, tool_name: str, args: Dict[str, Any]) -> Any:
        """Call a Sources MCP tool.

        Notes:
        - Uses a per-call stdio session for reliability.
        - Best-effort sync of corr_id inside the Sources process.
        """
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client

        async with self._io_lock:
            server = self._server_params()
            async with stdio_client(server) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()

                    # Keep Sources corr_id aligned with current request context.
                    # Never fail the caller because corr-id sync failed.
                    corr_id = get_request_id()
                    if corr_id and tool_name != "sources.context.set.v1":
                        try:
                            await session.call_tool("sources.context.set.v1", {"corr_id": corr_id})
                        except Exception:
                            pass

                    res = await session.call_tool(tool_name, args)
                    return self._unwrap_result(res)

    async def list_tools(self) -> Any:
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client

        async with self._io_lock:
            server = self._server_params()
            async with stdio_client(server) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    return await session.list_tools()

    async def close(self) -> None:
        """Kept for API compatibility; per-call mode has nothing to close."""
        return None
