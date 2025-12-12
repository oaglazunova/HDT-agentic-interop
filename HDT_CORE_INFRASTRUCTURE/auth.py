from functools import wraps
from flask import request
import logging

def authenticate_and_authorize(external_parties, user_permissions, required_permission):
    """
    Decorator factory to authenticate and authorize based on required_permission.

    Canonical client header is Authorization: Bearer <token>. The server also accepts
    X-API-KEY (and x-api-key) for compatibility during migration. Prefer Authorization
    in client code; X-API-KEY may be removed in a future version.

    - Accepts Authorization: Bearer <token> OR X-API-KEY / x-api-key
    - Matches provided token against entry.api_key OR entry.client_id
    - Supports external_parties as {'external_parties': [...]} or just [...]
    """
    # Normalize external_parties to a list once
    if isinstance(external_parties, dict):
        parties = external_parties.get("external_parties", []) or []
    else:
        parties = external_parties or []

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # ---- 1) Extract API key from headers (and allow ?api_key=... in dev) ----
            api_key = None

            # Authorization: Bearer <token> (canonical)
            auth_header = request.headers.get("Authorization")
            if auth_header and auth_header.lower().startswith("bearer "):
                api_key = auth_header.split(" ", 1)[1].strip()

            # X-API-KEY (compatibility; keep accepting during migration)
            if not api_key:
                api_key = request.headers.get("X-API-KEY") or request.headers.get("x-api-key")

            # (optional) allow query param in local/dev
            if not api_key:
                api_key = request.args.get("api_key")

            if not api_key:
                logging.debug("API key is missing in the request.")
                # Use json_with_headers for consistent headers
                try:
                    from HDT_CORE_INFRASTRUCTURE.HDT_API import json_with_headers
                except Exception:
                    from .HDT_API import json_with_headers

                return json_with_headers(
                    {"error": {"code": "missing_api_key", "message": "API key is missing"}},
                    status=401,
                    policy="deny",
                )

            # ---- 2) Verify key against api_key OR client_id (robust) ----
            client = next(
                (c for c in parties if (c.get("api_key") or c.get("client_id")) == api_key),
                None
            )
            if not client:
                logging.debug("Invalid API key provided.")
                try:
                    from HDT_CORE_INFRASTRUCTURE.HDT_API import json_with_headers
                except Exception:
                    from .HDT_API import json_with_headers

                return json_with_headers(
                    {"error": {"code": "invalid_api_key", "message": "Invalid API key"}},
                    status=401,
                    policy="deny",
                )

            # ---- 3) Authorization: compute accessible user IDs ----
            accessible_user_ids = []
            for user_id_str, perms in (user_permissions or {}).items():
                allowed_by_client = perms.get("allowed_clients", {})
                if client.get("client_id") in allowed_by_client:
                    if required_permission in allowed_by_client[client["client_id"]]:
                        try:
                            accessible_user_ids.append(int(user_id_str))
                        except ValueError:
                            logging.warning(f"Invalid user_id format: {user_id_str}")

            if not accessible_user_ids:
                logging.debug("No permissions set for this user/client/permission.")
                try:
                    from HDT_CORE_INFRASTRUCTURE.HDT_API import json_with_headers
                except Exception:
                    from .HDT_API import json_with_headers

                return json_with_headers(
                    {"error": {"code": "forbidden", "message": "No permissions set for this user"}},
                    status=403,
                    policy="deny",
                )

            # Attach context
            request.client = client
            request.accessible_user_ids = accessible_user_ids
            logging.debug(
                f"Client '{client.get('client_id')}' → users {accessible_user_ids} for '{required_permission}'"
            )
            return f(*args, **kwargs)
        return decorated_function
    return decorator
