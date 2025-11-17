# creates any missing files above (and a minimal static/index.html) so the repo "just works"

from __future__ import annotations
import json, os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CFG  = ROOT / "config"
STATIC = ROOT / "static"
CFG.mkdir(parents=True, exist_ok=True)
STATIC.mkdir(parents=True, exist_ok=True)

files = {
    CFG / "external_parties.json": {
        "external_parties": [
            {
                "client_id": "MODEL_DEVELOPER_1",
                "api_key": "MODEL_DEVELOPER_1",
                "permissions": [
                    "get_walk_data",
                    "get_trivia_data",
                    "get_sugarvita_data",
                    "get_sugarvita_player_types",
                    "get_health_literacy_diabetes"
                ]
            }
        ]
    },
    CFG / "user_permissions.json": {
        "2": {
            "allowed_clients": {
                "MODEL_DEVELOPER_1": [
                    "get_walk_data",
                    "get_trivia_data",
                    "get_sugarvita_data",
                    "get_sugarvita_player_types",
                    "get_health_literacy_diabetes"
                ]
            }
        },
        "3": {
            "allowed_clients": {
                "MODEL_DEVELOPER_1": [
                    "get_walk_data"
                ]
            }
        }
    },
    CFG / "users.json": {
        "users": [
            {
                "user_id": 2,
                "connected_apps_walk_data": [
                    { "connected_application": "Placeholder Walk", "player_id": "demo-1" }
                ]
            },
            {
                "user_id": 3,
                "connected_apps_walk_data": [
                    { "connected_application": "Placeholder walk app", "player_id": "demo" }
                ]
            }
        ]
    },
    CFG / "users.secrets.json": { "users": [] },
    CFG / "policy.json": {
        "defaults": {
            "analytics": { "allow": True, "redact": [] },
            "modeling":  { "allow": True, "redact": [] },
            "coaching":  { "allow": True, "redact": [] }
        },
        "clients": {},
        "tools": {}
    },
}

index_html = STATIC / "index.html"
index_html_contents = """<!doctype html>
<html><head><meta charset="utf-8"><title>HDT API</title></head>
<body><h1>HDT API</h1><p>Try <code>/healthz</code> or <code>/metadata/model_developer_apis</code>.</p></body></html>
"""

def write_json(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

def main():
    created = []
    for p, obj in files.items():
        if not p.exists():
            write_json(p, obj)
            created.append(p.name)
    if not index_html.exists():
        index_html.write_text(index_html_contents, encoding="utf-8")
        created.append(index_html.relative_to(ROOT).as_posix())

    if created:
        print("Created:", ", ".join(created))
    else:
        print("All sample config files already exist – nothing to do.")

if __name__ == "__main__":
    main()
