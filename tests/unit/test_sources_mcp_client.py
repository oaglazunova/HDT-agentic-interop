import pytest
from hdt_mcp.core.context import set_request_id


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
        if name == "sources.context.set@v1":
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
    from hdt_mcp.sources_mcp_client import SourcesMCPClient

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

    out = await client.call_tool("source.gamebus.walk.fetch@v1", {"user_id": 1})
    assert isinstance(out, str)
    assert '"ok"' in out

    # We should have tried close+connect once due to the injected failure.
    assert close_calls["n"] == 1
    assert connect_calls["n"] >= 1
