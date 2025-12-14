from __future__ import annotations

import os
from pathlib import Path

from flask import Blueprint, send_from_directory

from ..http import api_error, json_with_headers
from ..openapi_spec import load_openapi_spec
from ..users_store import UsersStore


def make_misc_blueprint(*, repo_root: Path, static_dir: Path, users_store: UsersStore) -> Blueprint:
    bp = Blueprint("misc", __name__)

    @bp.get("/")
    def index():
        return send_from_directory(str(static_dir), "index.html")

    @bp.get("/openapi.yaml")
    def openapi_yaml():
        return send_from_directory(str(repo_root), "openapi.yaml", mimetype="text/yaml")

    @bp.get("/openapi.json")
    def openapi_json():
        spec = load_openapi_spec(repo_root)
        return json_with_headers(spec, policy="info")

    @bp.get("/docs")
    def api_docs():
        return send_from_directory(str(static_dir), "docs/index.html")

    @bp.get("/healthz")
    def healthz():
        return json_with_headers({"status": "ok"}, policy="info")

    @bp.get("/__debug/effective_user/<int:user_id>")
    def debug_effective_user(user_id: int):
        if os.getenv("DEBUG_USERS", "0").strip().lower() not in ("1", "true", "yes"):
            return api_error("disabled", "Debug endpoint is disabled", status=404, policy="info")
        u = users_store.users.get(int(user_id))
        return json_with_headers(u or {}, policy="info")

    return bp
