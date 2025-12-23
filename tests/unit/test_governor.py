from __future__ import annotations

import pytest

from hdt_mcp.mcp_governor import HDTGovernor


class FakeSourcesClient:
    """In-memory SourcesMCPClient replacement for unit tests."""

    def __init__(self, responses: dict[str, object]):
        self._responses = responses
        self.calls: list[tuple[str, dict]] = []

    async def call_tool(self, tool_name: str, args: dict):
        self.calls.append((tool_name, dict(args)))
        resp = self._responses.get(tool_name)
        if callable(resp):
            out = resp(tool_name, args)
            if hasattr(out, "__await__"):
                return await out
            return out
        return resp


@pytest.mark.asyncio
async def test_sources_status_passthrough(monkeypatch):
    # Patch the SourcesMCPClient constructor used inside HDTGovernor
    fake = FakeSourcesClient({"sources.status.v1": {"ok": True, "user_id": 1}})
    monkeypatch.setattr("hdt_mcp.mcp_governor.SourcesMCPClient", lambda: fake)

    gov = HDTGovernor()
    out = await gov.sources_status(1)

    assert out["ok"] is True
    assert out["user_id"] == 1
    assert fake.calls == [("sources.status.v1", {"user_id": 1})]


@pytest.mark.asyncio
async def test_fetch_walk_prefers_gamebus(monkeypatch):
    # Ensure vault is not used in this unit test
    monkeypatch.setenv("HDT_VAULT_ENABLE", "0")

    fake = FakeSourcesClient(
        {
            "source.gamebus.walk.fetch.v1": {"records": [{"date": "2025-12-10", "steps": 1234}]},
            "source.googlefit.walk.fetch.v1": {"records": [{"date": "2025-12-10", "steps": 999}]},
        }
    )
    monkeypatch.setattr("hdt_mcp.mcp_governor.SourcesMCPClient", lambda: fake)

    gov = HDTGovernor()
    out = await gov.fetch_walk(user_id=1, limit=5, prefer="gamebus", prefer_data="live")

    assert out["selected_source"] == "gamebus"
    assert out["records"][0]["steps"] == 1234
    assert out["attempts"][0]["source"] == "gamebus"
    assert out["attempts"][0]["ok"] is True

    # Verify it called only the preferred live source (because it succeeded)
    assert fake.calls[0][0] == "source.gamebus.walk.fetch.v1"


@pytest.mark.asyncio
async def test_fetch_walk_falls_back_to_second_source(monkeypatch):
    monkeypatch.setenv("HDT_VAULT_ENABLE", "0")

    fake = FakeSourcesClient(
        {
            "source.gamebus.walk.fetch.v1": {"error": {"code": "upstream", "message": "fail"}},
            "source.googlefit.walk.fetch.v1": {"records": [{"date": "2025-12-10", "steps": 2222}]},
        }
    )
    monkeypatch.setattr("hdt_mcp.mcp_governor.SourcesMCPClient", lambda: fake)

    gov = HDTGovernor()
    out = await gov.fetch_walk(user_id=1, limit=5, prefer="gamebus", prefer_data="live")

    assert out["selected_source"] == "googlefit"
    assert out["records"][0]["steps"] == 2222
    assert [c[0] for c in fake.calls] == [
        "source.gamebus.walk.fetch.v1",
        "source.googlefit.walk.fetch.v1",
    ]
    assert out["attempts"][0]["ok"] is False
    assert out["attempts"][1]["ok"] is True
