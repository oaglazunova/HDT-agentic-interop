from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path

from flask import Flask, request

from .config_loader import load_external_parties, load_user_permissions

from .routes import (
    make_app_developer_blueprint,
    make_metadata_blueprint,
    make_misc_blueprint,
    make_model_developer_blueprint,
)
from .users_store import UsersStore


def create_app() -> Flask:
    """Flask application factory.

    Keeping initialization inside create_app() makes:
    - imports cheap
    - testing easier
    - `python -m hdt_api.app` reliable
    """

    app = Flask(__name__)

    # --- logging -------------------------------------------------------------
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper())
    app.logger.setLevel(logging.getLogger().level)

    repo_root = Path(__file__).resolve().parents[1]
    static_dir = repo_root / "static"
    config_dir = repo_root / "config"

    # --- config files --------------------------------------------------------
    external_parties = load_external_parties(repo_root)
    if isinstance(external_parties, dict):
        external_parties = external_parties.get("external_parties", []) or []

    user_permissions = load_user_permissions(repo_root)

    app.logger.info(
        "Loaded %d external parties: %s",
        len(external_parties),
        [(p.get("client_id"), "<key>") for p in external_parties],
    )
    app.logger.info("Loaded %d user-permission entries", len(user_permissions))

    users_public = config_dir / "users.json"
    users_secrets = config_dir / "users.secrets.json"
    users_store = UsersStore.from_files(
        public_path=users_public,
        secrets_path=users_secrets,
        logger=app.logger,
    )

    # --- middleware (request id + CORS) -------------------------------------
    @app.before_request
    def ensure_request_id() -> None:
        rid = (
            request.headers.get("X-Request-Id")
            or request.headers.get("X-Correlation-Id")
            or uuid.uuid4().hex
        )
        setattr(request, "request_id", rid)

    @app.after_request
    def add_cors_headers(resp):
        resp.headers.setdefault("Access-Control-Allow-Methods", "GET,OPTIONS")
        resp.headers.setdefault(
            "Access-Control-Allow-Headers",
            "Authorization, X-API-KEY, Content-Type, If-None-Match, X-Request-Id, X-Correlation-Id",
        )
        # Ensure X-Request-Id is always present (even for OPTIONS or non-JSON responses)
        rid = getattr(request, "request_id", None)
        if rid and "X-Request-Id" not in resp.headers:
            resp.headers["X-Request-Id"] = rid

        resp.headers.setdefault(
            "Access-Control-Expose-Headers",
            "ETag, X-Client-Id, X-Users-Count, X-Policy, X-Request-Id, Link, X-Limit, X-Offset, X-Total",
        )
        return resp

    # --- routes --------------------------------------------------------------
    app.register_blueprint(make_metadata_blueprint())

    app.register_blueprint(
        make_model_developer_blueprint(
            external_parties=external_parties,
            user_permissions=user_permissions,
            users_store=users_store,
        )
    )

    app.register_blueprint(
        make_app_developer_blueprint(
            external_parties=external_parties,
            user_permissions=user_permissions,
            repo_root=repo_root,
        )
    )

    app.register_blueprint(
        make_misc_blueprint(repo_root=repo_root, static_dir=static_dir, users_store=users_store)
    )

    # OPTIONS preflight (global)
    @app.route("/<path:_any>", methods=["OPTIONS"])
    def any_options(_any: str):
        return ("", 204)

    return app


def main() -> None:
    app = create_app()
    host = os.getenv("HDT_API_HOST", "0.0.0.0")
    port = int(os.getenv("HDT_API_PORT", "5000"))
    debug = (os.getenv("HDT_API_DEBUG", "0").lower() in ("1", "true", "yes"))

    print(f"Starting the HDT API server on http://{host}:{port}")
    print("Press Ctrl+C to stop the server")
    app.run(debug=debug, host=host, port=port)


if __name__ == "__main__":
    main()
