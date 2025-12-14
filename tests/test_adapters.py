import sys
import types


def test_gamebus_adapter_monkeypatched_module(monkeypatch):
    # Create a fake provider module with expected function
    mod = types.ModuleType("GAMEBUS_WALK_fetch")
    def fetch_walk_data(player_id, auth_bearer=None):
        return [{"date": "2025-11-03", "steps": 321}]
    mod.fetch_walk_data = fetch_walk_data

    # Install it under the expected absolute name
    sys.modules["hdt_api.GAMEBUS_WALK_fetch"] = mod

    from hdt_mcp.adapters.gamebus import fetch_walk
    out = fetch_walk("p-1", auth_bearer=None)
    assert out and out[0]["steps"] == 321


def test_google_fit_adapter_monkeypatched_module(monkeypatch):
    mod = types.ModuleType("GOOGLE_FIT_WALK_fetch")
    def fetch_google_fit_walk_data(player_id, auth_bearer=None):
        return [{"date": "2025-11-04", "steps": 654}]
    mod.fetch_google_fit_walk_data = fetch_google_fit_walk_data

    sys.modules["hdt_api.GOOGLE_FIT_WALK_fetch"] = mod

    from hdt_mcp.adapters.google_fit import fetch_walk
    out = fetch_walk("p-2", auth_bearer=None)
    assert out and out[0]["steps"] == 654
