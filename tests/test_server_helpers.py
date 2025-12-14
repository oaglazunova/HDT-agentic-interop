import json
from pathlib import Path


def _write_users_cfg(base: Path, users_obj: dict):
    cfg_dir = base / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "users.json").write_text(json.dumps(users_obj), encoding="utf-8")


def test_resolve_connected_app_unknown(monkeypatch, tmp_path):
    # No connected apps -> returns fallback tuple
    users = {"users": [{"user_id": 1, "connected_apps_walk_data": []}]}
    _write_users_cfg(tmp_path, users)
    monkeypatch.chdir(tmp_path)

    from hdt_mcp.server_helpers import resolve_connected_app

    name, pid, token = resolve_connected_app(1, "walk_data")
    assert name == "Unknown"
    assert pid is None and token is None


def test_resolve_connected_app_happy_path(monkeypatch, tmp_path):
    users = {
        "users": [
            {
                "user_id": 2,
                "connected_apps_walk_data": [
                    {
                        "connected_application": "GameBus",
                        "player_id": "p-2",
                        "auth_bearer": "tkn-2",
                    }
                ],
            }
        ]
    }
    _write_users_cfg(tmp_path, users)
    monkeypatch.chdir(tmp_path)

    from hdt_mcp.server_helpers import resolve_connected_app

    name, pid, token = resolve_connected_app(2, "walk_data")
    assert name == "GameBus"
    assert pid == "p-2"
    assert token == "tkn-2"
