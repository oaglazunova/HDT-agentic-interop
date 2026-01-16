import pytest
from hdt_common.context import set_request_id
from hdt_mcp.sources_mcp_client import SourcesMCPClient


class _FakeResult:
    def __init__(self, text: str):
        self.content = [{"text": text}]


class _FakeSessionFailOnceGlobal:
    """
    Fails exactly once across reconnections, then succeeds.
    Uses shared fail_state so a new session after reconnect won't fail again.
    """
    def __init__(self, fail_state: dict):
        self.fail_state = fail_state
        self.calls = []

    async def call_tool(self, name, args):
        self.calls.append((name, args))

        # corr-id sync tool should always succeed
        if name == "sources.context.set.v1":
            return _FakeResult("ok")

        # fail exactly once overall
        if not self.fail_state["failed"]:
            self.fail_state["failed"] = True
            raise RuntimeError("boom")

        return _FakeResult('{"ok": true}')

    async def list_tools(self):
        return {"tools": ["a", "b"]}


@pytest.mark.asyncio
async def test_call_tool_invokes_corr_id_sync_then_tool(monkeypatch):
    """Per-call stdio session: ensure corr-id sync is attempted and tool is invoked."""
    set_request_id("CID-1")
    client = SourcesMCPClient()

    calls: list[tuple[str, dict]] = []

    class _FakeClientSession:
        def __init__(self, read, write):
            self.read = read
            self.write = write

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def initialize(self):
            return None

        async def call_tool(self, name, args):
            calls.append((name, dict(args)))
            if name == "sources.context.set.v1":
                return _FakeResult("ok")
            return _FakeResult('{"ok": true}')

    class _FakeStdioCM:
        async def __aenter__(self):
            return (object(), object())

        async def __aexit__(self, exc_type, exc, tb):
            return False

    def _fake_stdio_client(server):
        return _FakeStdioCM()

    import mcp
    import mcp.client.stdio as stdio_mod
    monkeypatch.setattr(mcp, "ClientSession", _FakeClientSession)
    monkeypatch.setattr(stdio_mod, "stdio_client", _fake_stdio_client)

    out = await client.call_tool("sources.status.v1", {"user_id": 1})
    assert isinstance(out, str)
    assert '"ok"' in out

    # First we sync corr_id, then call the requested tool.
    assert calls[0][0] == "sources.context.set.v1"
    assert calls[0][1]["corr_id"] == "CID-1"
    assert calls[1][0] == "sources.status.v1"
    assert calls[1][1] == {"user_id": 1}


class _FakeStdioCM:
    def __init__(self):
        self.exited = 0

    async def __aexit__(self, exc_type, exc, tb):
        self.exited += 1


class _FakeSessionForClose:
    def __init__(self):
        self.exited = 0

    async def __aexit__(self, exc_type, exc, tb):
        self.exited += 1


class _FakeSessionForListTools:
    async def list_tools(self):
        return {"tools": ["a", "b"]}


def test_server_params_sets_env(monkeypatch):
    """
    Covers _server_params() env construction (corr_id, telemetry dir, stdio transport).
    Does not spawn anything.
    """
    set_request_id("CID-TEST-1")
    client = SourcesMCPClient()

    # Patch StdioServerParameters to avoid depending on MCP internals
    class _FakeParams:
        def __init__(self, command, args, env):
            self.command = command
            self.args = args
            self.env = env

    import mcp.client.stdio as stdio_mod
    monkeypatch.setattr(stdio_mod, "StdioServerParameters", _FakeParams)

    params = client._server_params()
    assert params.env["MCP_TRANSPORT"] == "stdio"
    assert params.env["HDT_CORR_ID"] == "CID-TEST-1"
    assert "HDT_TELEMETRY_DIR" in params.env


@pytest.mark.asyncio
async def test_close_is_noop():
    """Per-call mode has nothing to close; close() should not raise."""
    client = SourcesMCPClient()
    await client.close()


@pytest.mark.asyncio
async def test_list_tools_returns_tools(monkeypatch):
    client = SourcesMCPClient()

    class _FakeClientSession:
        def __init__(self, read, write):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def initialize(self):
            return None

        async def list_tools(self):
            return {"tools": ["a", "b"]}

    class _FakeStdioCM:
        async def __aenter__(self):
            return (object(), object())

        async def __aexit__(self, exc_type, exc, tb):
            return False

    def _fake_stdio_client(server):
        return _FakeStdioCM()

    import mcp
    import mcp.client.stdio as stdio_mod
    monkeypatch.setattr(mcp, "ClientSession", _FakeClientSession)
    monkeypatch.setattr(stdio_mod, "stdio_client", _fake_stdio_client)

    out = await client.list_tools()
    assert out == {"tools": ["a", "b"]}
