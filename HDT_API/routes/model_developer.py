from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from flask import Blueprint, request

from ..http import api_error, json_with_headers
from ..users_store import UsersStore


def make_model_developer_blueprint(
    *,
    external_parties: List[Mapping[str, Any]],
    user_permissions: Mapping[str, Any],
    users_store: UsersStore,
) -> Blueprint:
    """Routes used by "model developers" (training/analytics consumers)."""
    # Late imports to keep app startup deterministic and avoid import-time side effects.
    from ..providers.gamebus.diabetes import fetch_sugarvita_data, fetch_trivia_data
    from ..auth import authenticate_and_authorize
    from ..services.fetchers import fetch_walk_batch
    from ..services.pagination import paginate, parse_pagination_args, set_next_link
    from ..validation import ValidationError, sanitize_walk_records

    bp = Blueprint("model_developer", __name__)

    def _fetch_gamebus_series(
        *,
        accessible_user_ids: List[int],
        app_type: str,
        fetch_fn: Callable[[str, Optional[str]], Tuple[Any, str]],
        not_found_message: str,
    ) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for uid in accessible_user_ids:
            app_name, player_id, auth_bearer = users_store.get_connected_app_info(uid, app_type)

            if app_name == "GameBus":
                data, latest_activity_info = fetch_fn(player_id, auth_bearer)
                if data:
                    out.append(
                        {
                            "user_id": uid,
                            "data": {"results": data, "latest_activity_info": latest_activity_info},
                            "error": None,
                        }
                    )
                else:
                    out.append(
                        {
                            "user_id": uid,
                            "error": {"code": "not_found", "message": not_found_message.format(uid=uid)},
                        }
                    )
            elif app_name == "Placeholder diabetes app":
                out.append(
                    {
                        "user_id": uid,
                        "error": {
                            "code": "unsupported_app",
                            "message": f"Support for '{app_name}' is not yet implemented.",
                        },
                    }
                )
            else:
                out.append(
                    {
                        "user_id": uid,
                        "error": {
                            "code": "not_connected",
                            "message": f"User {uid} does not have a connected diabetes application.",
                        },
                    }
                )
        return out

    @bp.get("/get_trivia_data")
    @authenticate_and_authorize(external_parties, user_permissions, "get_trivia_data")
    def get_trivia_data():
        try:
            accessible_user_ids = request.accessible_user_ids
            response_data = _fetch_gamebus_series(
                accessible_user_ids=accessible_user_ids,
                app_type="diabetes_data",
                fetch_fn=fetch_trivia_data,
                not_found_message="No data found for user {uid}",
            )

            # Keep original contract (field names) to avoid client breakage
            for env in response_data:
                if env.get("data") and "results" in env["data"]:
                    env["data"] = {
                        "trivia_results": env["data"]["results"],
                        "latest_activity_info": env["data"]["latest_activity_info"],
                    }

            return json_with_headers(response_data, policy="passthrough")
        except Exception as e:
            logging.error(f"[rid={getattr(request, 'request_id', '-')}] Error in get_trivia_data: {e}")
            return api_error("internal", "Internal server error", status=500)

    @bp.get("/get_sugarvita_data")
    @authenticate_and_authorize(external_parties, user_permissions, "get_sugarvita_data")
    def get_sugarvita_data():
        try:
            accessible_user_ids = request.accessible_user_ids
            response_data = _fetch_gamebus_series(
                accessible_user_ids=accessible_user_ids,
                app_type="diabetes_data",
                fetch_fn=fetch_sugarvita_data,
                not_found_message="No data found for user {uid}",
            )

            for env in response_data:
                if env.get("data") and "results" in env["data"]:
                    env["data"] = {
                        "sugarvita_results": env["data"]["results"],
                        "latest_activity_info": env["data"]["latest_activity_info"],
                    }

            return json_with_headers(response_data, policy="passthrough")
        except Exception as e:
            logging.error(f"[rid={getattr(request, 'request_id', '-')}] Error in get_sugarvita_data: {e}")
            return api_error("internal", "Internal server error", status=500)

    @bp.get("/get_walk_data")
    @authenticate_and_authorize(external_parties, user_permissions, "get_walk_data")
    def get_walk_data():
        try:
            accessible_user_ids = getattr(request, "accessible_user_ids", [])
            user_id = request.args.get("user_id", type=int)

            limit, offset, err = parse_pagination_args()
            if err:
                msg, code = err
                return api_error("bad_input", msg, status=code)

            from_iso = request.args.get("from")
            to_iso = request.args.get("to")

            # -------- Single-user ----------
            if user_id is not None:
                if user_id not in accessible_user_ids:
                    return api_error("forbidden", f"User {user_id} not permitted", status=403, policy="deny")

                res = fetch_walk_batch(user_id, limit, offset, from_iso=from_iso, to_iso=to_iso)
                try:
                    cleaned = sanitize_walk_records(res.get("records", []))
                except ValidationError as e:
                    return api_error("bad_input", str(e), status=400)

                page, has_next = paginate(res.get("total"), limit, offset)

                payload = {"user_id": user_id, "records": cleaned, "page": page, "error": None}
                extra = {"X-Limit": str(page.get("limit", "")), "X-Offset": str(page.get("offset", ""))}
                if page.get("total") is not None:
                    extra["X-Total"] = str(page["total"])

                resp = json_with_headers(
                    [payload],
                    policy="passthrough",
                    extra_headers=extra,
                    etag_variant={
                        "policy": "passthrough",
                        "user_id": user_id,
                        "limit": limit,
                        "offset": offset,
                        "from": from_iso,
                        "to": to_iso,
                    },
                )
                if has_next:
                    resp = set_next_link(resp, request.base_url, limit, offset + limit)
                return resp

            # -------- Multi-user ----------
            envelopes: List[Dict[str, Any]] = []
            any_has_next = False

            for uid in accessible_user_ids:
                res = fetch_walk_batch(uid, limit, offset, from_iso=from_iso, to_iso=to_iso)
                try:
                    cleaned = sanitize_walk_records(res.get("records", []))
                except ValidationError as e:
                    envelopes.append({"user_id": uid, "error": {"code": "bad_input", "message": str(e)}})
                    continue

                page, has_next = paginate(res.get("total"), limit, offset)
                any_has_next = any_has_next or has_next
                envelopes.append({"user_id": uid, "records": cleaned, "page": page, "error": None})

            resp = json_with_headers(
                envelopes,
                policy="passthrough",
                etag_variant={
                    "policy": "passthrough",
                    "limit": limit,
                    "offset": offset,
                    "from": from_iso,
                    "to": to_iso,
                },
            )
            if any_has_next:
                resp = set_next_link(resp, request.base_url, limit, offset + limit)
            return resp

        except Exception:
            logging.exception(f"[rid={getattr(request, 'request_id', '-')}] Error in get_walk_data")
            return api_error("internal", "Internal server error", status=500)

    return bp
