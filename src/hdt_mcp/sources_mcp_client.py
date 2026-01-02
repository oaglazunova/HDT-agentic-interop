from __future__ import annotations

import asyncio
import os
import sys
from typing import Any, Dict, Optional, TYPE_CHECKING

from hdt_config.settings import repo_root
from hdt_common.context import get_request_id, new_request_id

if TYPE_CHECKING:
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters

class SourcesMCPClient:
    """
    Stdio MCP client for talking to the internal Sources MCP server.

    Key behavior:
    - Spawns the Sources MCP process once (lazily) and keeps a long-lived ClientSession.
    - Serializes requests through a lock (stdio is effectively a single shared channel).
    - Reconnects (best-effort) on failure.
    - Optionally updates the Sources process correlation id via the internal tool
      `sources.context.set.v1` when the external corr_id changes.
    """

    def __init__(self) -> None:
        # Use the active interpreter (venv-safe). You can override via MCP_SOURCES_PYTHON.
        self._command = os.getenv("MCP_SOURCES_PYTHON") or sys.executable
        self._args = ["-m", "hdt_sources_mcp.server"]
        # Put Sources telemetry in its own directory to avoid Windows file contention.
        root = repo_root()
        self._sources_telemetry_dir = str((root / "artifacts" / "telemetry" / "sources_mcp").resolve())

        # Long-lived connection state
        self._stdio_cm = None  # async context manager from stdio_client(...)
        self._session: Optional["ClientSession"] = None

        # Concurrency / lifecycle
        self._connect_lock = asyncio.Lock()
        self._io_lock = asyncio.Lock()

        # Correlation id tracking (optional context sync)
        self._last_corr_id: Optional[str] = None

    def _server_params(self):
        # Lazy import
        from mcp.client.stdio import StdioServerParameters

        corr_id = get_request_id()
        if not corr_id:
            corr_id = new_request_id()
            # If needed, explicitly set the context here.

        env = dict(os.environ)
        env["MCP_TRANSPORT"] = "stdio"
        env["HDT_TELEMETRY_DIR"] = self._sources_telemetry_dir
        env["HDT_CORR_ID"] = corr_id

        return StdioServerParameters(command=self._command, args=self._args, env=env)

    async def _connect(self) -> None:
        # Lazy imports
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client

        if self._session is not None:
            return

        async with self._connect_lock:
            if self._session is not None:
                return

            server = self._server_params()
            self._stdio_cm = stdio_client(server)

            session = None
            try:
                read, write = await self._stdio_cm.__aenter__()

                session = ClientSession(read, write)
                await session.__aenter__()
                await session.initialize()

                self._session = session
                await self._sync_corr_id_locked(force=True)

            except Exception:
                try:
                    if session is not None:
                        await session.__aexit__(None, None, None)
                finally:
                    self._session = None

                try:
                    if self._stdio_cm is not None:
                        await self._stdio_cm.__aexit__(None, None, None)
                finally:
                    self._stdio_cm = None

                raise


    async def _close(self) -> None:
        async with self._connect_lock:
            # Close session first, then the underlying stdio client.
            if self._session is not None:
                try:
                    await self._session.__aexit__(None, None, None)
                finally:
                    self._session = None

            if self._stdio_cm is not None:
                try:
                    await self._stdio_cm.__aexit__(None, None, None)
                finally:
                    self._stdio_cm = None

            self._last_corr_id = None

    async def close(self) -> None:
        """
        Public close hook (optional). Not required in typical server operation,
        but useful for tests or graceful shutdown hooks.
        """
        async with self._io_lock:
            await self._close()

    async def _sync_corr_id_locked(self, *, force: bool = False) -> None:
        """
        Update corr_id inside the Sources MCP process so its telemetry aligns with
        the current external request context.

        Must be called with _io_lock held and after _connect().
        """
        if self._session is None:
            return

        corr_id = get_request_id()
        if not corr_id:
            return

        if not force and corr_id == self._last_corr_id:
            return

        # This tool is implemented in hdt_sources_mcp/server.py
        try:
            await self._session.call_tool("sources.context.set.v1", {"corr_id": corr_id})
            self._last_corr_id = corr_id
        except Exception:
            # Never fail the caller because corr-id sync failed.
            self._last_corr_id = corr_id

    @staticmethod
    def _unwrap_result(res: Any) -> Any:
        content = getattr(res, "content", None)
        if not content:
            return res

        c0 = content[0]
        if isinstance(c0, dict) and "text" in c0:
            return c0["text"]
        return getattr(c0, "text", c0)

    async def call_tool(self, tool_name: str, args: Dict[str, Any]) -> Any:
        """
        Call a Sources MCP tool over a long-lived session. Automatically reconnects once
        on failure.
        """
        # Serialize IO: stdio transport is effectively a single channel.
        async with self._io_lock:
            await self._connect()

            # Keep Sources corr_id in sync with hdt_mcp corr_id (best-effort).
            if tool_name != "sources.context.set.v1":
                await self._sync_corr_id_locked()

            assert self._session is not None
            try:
                res = await self._session.call_tool(tool_name, args)
                return self._unwrap_result(res)
            except Exception:
                # One reconnect attempt, then re-raise
                await self._close()
                await self._connect()

                # Re-sync corr_id after reconnect (best-effort)
                if tool_name != "sources.context.set.v1":
                    await self._sync_corr_id_locked(force=True)

                assert self._session is not None
                res = await self._session.call_tool(tool_name, args)
                return self._unwrap_result(res)

    async def list_tools(self) -> Any:
        async with self._io_lock:
            await self._connect()
            assert self._session is not None
            return await self._session.list_tools()
