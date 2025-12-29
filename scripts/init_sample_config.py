"""Initialize sample config files for local runs and paper demos.

This script creates/updates:
  - config/users.json
  - config/users.secrets.json

The generated files contain placeholders only and are safe to share.
In real deployments, secrets should be stored outside the repository.

Usage:
  python scripts/init_sample_config.py
  python scripts/init_sample_config.py --force
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from hdt_config.settings import repo_root, config_dir


def _write_json(path: Path, obj: dict, *, force: bool) -> None:
    if path.exists() and not force:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="Overwrite existing files")
    args = ap.parse_args()

    root = repo_root()
    cfg = config_dir()

    users_path = cfg / "users.json"
    secrets_path = cfg / "users.secrets.json"

    users = {
        "users": [
            {
                "user_id": 1,
                "email": "synthetic.user@example.org",
                "note": "Synthetic demo user (no real data)",
                "connected_apps_walk_data": [
                    {"connected_application": "GameBus", "player_id": "MOCK_PLAYER_123"},
                    {"connected_application": "Google Fit", "player_id": "MOCK_PLAYER_123"}
                ],
                "connected_apps_diabetes_data": [
                    {"connected_application": "GameBus", "player_id": "MOCK_PLAYER_123"}
                ]
            }
        ]
    }

    secrets = {
        "users": [
            {
                "user_id": 1,
                "connected_apps_walk_data": [
                    {
                        "connected_application": "GameBus",
                        "player_id": "MOCK_PLAYER_123",
                        "auth_bearer": "YOUR_GAMEBUS_TOKEN_HERE"
                    },
                    {
                        "connected_application": "Google Fit",
                        "player_id": "MOCK_PLAYER_123",
                        "auth_bearer": "YOUR_GOOGLE_FIT_TOKEN_HERE"
                    }
                ],
                "connected_apps_diabetes_data": [
                    {
                        "connected_application": "GameBus",
                        "player_id": "MOCK_PLAYER_123",
                        "auth_bearer": "YOUR_GAMEBUS_DIABETES_TOKEN_HERE"
                    }
                ]
            }
        ]
    }

    _write_json(users_path, users, force=args.force)
    _write_json(secrets_path, secrets, force=args.force)

    print(f"Repo root: {root}")
    print(f"Wrote (or kept existing): {users_path}")
    print(f"Wrote (or kept existing): {secrets_path}")
    print("\nNotes:")
    print("- These are placeholders only.")
    print("- For deterministic offline demos (and to avoid external systems), use the seeded vault (prefer_data=vault).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
