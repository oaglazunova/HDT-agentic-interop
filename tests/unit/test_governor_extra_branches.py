from __future__ import annotations

import pytest

import hdt_mcp.governor as mg


@pytest.mark.asyncio
async def test_fetch_walk_vault_only_empty_returns_typed_error(monkeypatch):
    """prefer_data=vault must fail fast when vault has no matching data."""
    # Avoid file telemetry writes during unit tests
    monkeypatch.setattr(mg, "log_event", lambda *a, **k: None)

    # Vault enabled but returns empty
    monkeypatch.setattr(mg.vault_store, "enabled", lambda: True)
    monkeypatch.setattr(
        mg.vault_store,
        "fetch_walk",
        lambda **kwargs: {"user_id": kwargs["user_id"], "kind": "walk", "records": []},
    )

    gov = mg.HDTGovernor()

    async def should_not_call(*a, **k):
        raise AssertionError("Sources MCP must not be called for prefer_data=vault when vault is empty")

    monkeypatch.setattr(gov.sources, "call_tool", should_not_call)

    out = await gov.fetch_walk(user_id=1, prefer_data="vault", purpose="analytics")
    assert isinstance(out, dict) and "error" in out
    assert out["error"]["code"] == "vault_empty"


def test_as_json_parses_json_text_and_preserves_non_json():
    assert mg._as_json('{"ok": true, "n": 1}') == {"ok": True, "n": 1}
    assert mg._as_json("not json") == "not json"


def test_shape_for_purpose_redacts_provenance_for_analytics():
    payload = {
        "user_id": 1,
        "kind": "walk",
        "selected_source": "gamebus",
        "attempts": [],
        "records": [{"steps": 1}],
        "provenance": {
            "player_id": "P1",
            "email": "x@y",
            "token": "SECRET",
            "account_user_id": "A1",
            "note": "keep",
        },
    }
    out = mg._shape_for_purpose(payload, "analytics")
    assert "error" not in out
    prov = out.get("provenance")
    assert isinstance(prov, dict)
    assert "note" in prov
    assert "player_id" not in prov
    assert "email" not in prov
    assert "token" not in prov
    assert "account_user_id" not in prov


def test_shape_for_purpose_handles_non_dict_provenance_and_denies_modeling_raw_fetch():
    payload = {
        "user_id": 1,
        "kind": "walk",
        "selected_source": "gamebus",
        "attempts": [],
        "records": [{"steps": 1}],
        "provenance": "opaque",
    }
    out = mg._shape_for_purpose(payload, "analytics")
    assert out.get("provenance") == "opaque"

    denied = mg._shape_for_purpose(payload, "modeling")
    assert "error" in denied
    assert denied["error"]["code"] == "not_supported"


def test_vault_helpers_cover_disabled_and_write_failure(monkeypatch):
    attempts: list[dict] = []

    # Vault disabled -> attempt is recorded
    monkeypatch.setattr(mg.vault_store, "enabled", lambda: False)
    out = mg._vault_try_read_walk(
        user_id=1,
        start_date=None,
        end_date=None,
        limit=None,
        offset=None,
        prefer_source="gamebus",
        attempts=attempts,
        label="vault",
    )
    assert out is None
    assert attempts[-1]["error"]["code"] == "vault_disabled"

    # Vault write failure -> recorded as a best-effort attempt
    monkeypatch.setattr(mg.vault_store, "enabled", lambda: True)

    def _boom(*a, **k):
        raise RuntimeError("nope")

    monkeypatch.setattr(mg.vault_store, "upsert_walk", _boom)
    mg._vault_try_write_walk(user_id=1, records=[{"steps": 1}], source="gamebus", attempts=attempts)
    assert any(a.get("source") == "vault_write" for a in attempts)


def test_walk_features_from_records_empty_branch():
    feats = mg._walk_features_from_records([{},{"steps": None},{"steps": "bad"}])
    assert feats == {"days": 0, "total_steps": 0, "avg_steps": 0}


@pytest.mark.asyncio
async def test_fetch_trivia_and_sugarvita_success_and_error_paths(monkeypatch):
    monkeypatch.setattr(mg, "log_event", lambda *a, **k: None)

    gov = mg.HDTGovernor()

    async def call_tool(tool_name: str, args: dict):
        # Return JSON text for trivia (covers _as_json JSON parsing)
        if tool_name.endswith("trivia.fetch.v1"):
            return '{"user_id": 1, "records": [{"q": "x"}]}'
        if tool_name.endswith("sugarvita.fetch.v1"):
            return {"error": {"code": "upstream", "message": "fail"}}
        raise AssertionError("Unexpected tool")

    monkeypatch.setattr(gov.sources, "call_tool", call_tool)

    ok = await gov.fetch_trivia(user_id=1, purpose="analytics")
    assert "error" not in ok
    assert ok.get("selected_source") == "gamebus"

    bad = await gov.fetch_sugarvita(user_id=1, purpose="analytics")
    assert "error" in bad
    assert bad["error"]["code"] == "upstream"


@pytest.mark.asyncio
async def test_walk_features_propagates_fetch_error_and_logs_exception(monkeypatch):
    monkeypatch.setattr(mg, "log_event", lambda *a, **k: None)

    gov = mg.HDTGovernor()

    async def fake_fetch_walk(*a, **k):
        return {"error": {"code": "upstream", "message": "fail"}, "user_id": 1}

    monkeypatch.setattr(gov, "fetch_walk", fake_fetch_walk)
    out = await gov.walk_features(user_id=1, purpose="modeling")
    assert "error" in out and out["error"]["code"] == "upstream"

    # Also cover exception branch that re-raises (and still executes finally)
    async def raising(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(gov, "fetch_walk", raising)
    with pytest.raises(RuntimeError):
        await gov.walk_features(user_id=1, purpose="modeling")
