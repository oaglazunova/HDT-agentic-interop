from typing import List


def test_sync_user_walk_routes(monkeypatch):
    # Stub adapter calls so no external I/O occurs
    from HDT_MCP.domain import services

    monkeypatch.setattr(
        "HDT_MCP.adapters.gamebus.fetch_walk",
        lambda player_id, auth_bearer=None: [{"date": "2025-11-01", "steps": 100}],
        raising=True,
    )
    monkeypatch.setattr(
        "HDT_MCP.adapters.google_fit.fetch_walk",
        lambda player_id, auth_bearer=None: [{"date": "2025-11-02", "steps": 200}],
        raising=True,
    )

    out_gamebus = services.sync_user_walk("gamebus", "p1", auth_bearer=None)
    out_google = services.sync_user_walk("google fit", "p2", auth_bearer=None)
    out_placeholder = services.sync_user_walk("placeholder-demo", "p3", auth_bearer=None)
    out_unknown = services.sync_user_walk("unknown", "p4", auth_bearer=None)

    assert out_gamebus and out_gamebus[0]["steps"] == 100
    assert out_google and out_google[0]["steps"] == 200
    assert isinstance(out_placeholder, list) and len(out_placeholder) >= 1
    assert out_unknown == []
