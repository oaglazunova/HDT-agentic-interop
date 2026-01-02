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
async def test_call_tool_reconnects_once(monkeypatch):
    set_request_id("CID-1")
    client = SourcesMCPClient()

    fail_state = {"failed": False}
    client._session = _FakeSessionFailOnceGlobal(fail_state)

    close_calls = {"n": 0}
    connect_calls = {"n": 0}

    async def fake_close():
        close_calls["n"] += 1
        client._session = None

    async def fake_connect():
        connect_calls["n"] += 1
        if client._session is None:
            client._session = _FakeSessionFailOnceGlobal(fail_state)

    monkeypatch.setattr(client, "_close", fake_close)
    monkeypatch.setattr(client, "_connect", fake_connect)

    out = await client.call_tool("source.gamebus.walk.fetch.v1", {"user_id": 1})
    assert isinstance(out, str)
    assert '"ok"' in out

    # We should have tried close+connect once due to the injected failure.
    assert close_calls["n"] == 1
    assert connect_calls["n"] >= 1


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
async def test_close_closes_session_and_stdio():
    """
    Covers close() -> _close() branches: session and stdio context manager teardown.
    """
    client = SourcesMCPClient()
    fake_session = _FakeSessionForClose()
    fake_stdio = _FakeStdioCM()

    client._session = fake_session
    client._stdio_cm = fake_stdio
    client._last_corr_id = "CID-OLD"

    await client.close()

    assert fake_session.exited == 1
    assert fake_stdio.exited == 1
    assert client._session is None
    assert client._stdio_cm is None
    assert client._last_corr_id is None


@pytest.mark.asyncio
async def test_list_tools_uses_session(monkeypatch):
    """
    Covers list_tools() method path without spawning a Sources process.
    """
    client = SourcesMCPClient()

    async def fake_connect():
        if client._session is None:
            client._session = _FakeSessionForListTools()

    monkeypatch.setattr(client, "_connect", fake_connect)

    out = await client.list_tools()
    assert out == {"tools": ["a", "b"]}
