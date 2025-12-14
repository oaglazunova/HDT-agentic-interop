from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, List, Mapping

from flask import Blueprint, request

from ..http import api_error, json_with_headers


def make_app_developer_blueprint(
    *,
    external_parties: List[Mapping[str, Any]],
    user_permissions: Mapping[str, Any],
    repo_root: Path,
) -> Blueprint:
    """Routes used by "app developers" (insights/derived metrics consumers)."""
    from ..auth import authenticate_and_authorize

    bp = Blueprint("app_developer", __name__)

    storage_file = repo_root / "diabetes_pt_hl_storage.json"

    def _load_storage() -> dict:
        try:
            return json.loads(storage_file.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise
        except Exception as e:
            raise RuntimeError(f"Invalid storage JSON: {e}")

    @bp.get("/get_sugarvita_player_types")
    @authenticate_and_authorize(external_parties, user_permissions, "get_sugarvita_player_types")
    def get_sugarvita_player_types():
        try:
            user_id = request.args.get("user_id", type=int)
            if user_id not in request.accessible_user_ids:
                return api_error("forbidden", "Unauthorized access to this user's data", status=403, policy="deny")

            try:
                storage_data = _load_storage()
            except FileNotFoundError as e:
                logging.error(f"[rid={getattr(request, 'request_id', '-')}] Storage file missing: {e}")
                return api_error("internal", "Internal server error", status=500)
            except Exception as e:
                logging.error(f"[rid={getattr(request, 'request_id', '-')}] Error loading storage: {e}")
                return api_error("internal", "Internal server error", status=500)

            user_data = storage_data.get("users", {}).get(str(user_id), {})
            if not user_data:
                return api_error("not_found", f"No data found for user {user_id}", status=404)

            if not user_data.get("entries"):
                return json_with_headers(
                    {"user_id": user_id, "latest_update": None, "player_types": {}},
                    policy="passthrough",
                )

            latest_entry = user_data["entries"][-1]
            player_types_labels = latest_entry.get("final_scores", {}).get("player_types_labels", {})
            latest_date = latest_entry.get("date")

            return json_with_headers(
                {"user_id": user_id, "latest_update": latest_date, "player_types": player_types_labels},
                policy="passthrough",
            )
        except Exception as e:
            logging.error(f"[rid={getattr(request, 'request_id', '-')}] Error in get_sugarvita_player_types: {e}")
            return api_error("internal", "Internal server error", status=500)

    @bp.get("/get_health_literacy_diabetes")
    @authenticate_and_authorize(external_parties, user_permissions, "get_health_literacy_diabetes")
    def get_health_literacy_diabetes():
        try:
            user_id = request.args.get("user_id", type=int)
            if user_id not in request.accessible_user_ids:
                return api_error("forbidden", "Unauthorized access to this user's data", status=403, policy="deny")

            try:
                storage_data = _load_storage()
            except FileNotFoundError as e:
                logging.error(f"[rid={getattr(request, 'request_id', '-')}] Storage file missing: {e}")
                return api_error("internal", "Internal server error", status=500)
            except Exception as e:
                logging.error(f"[rid={getattr(request, 'request_id', '-')}] Error loading storage: {e}")
                return api_error("internal", "Internal server error", status=500)

            user_data = storage_data.get("users", {}).get(str(user_id), {})
            if not user_data:
                return api_error("not_found", f"No data found for user {user_id}", status=404)

            if not user_data.get("entries"):
                return json_with_headers(
                    {"user_id": user_id, "latest_update": None, "health_literacy_score": None},
                    policy="passthrough",
                )

            latest_entry = user_data["entries"][-1]
            hl_score = (
                latest_entry.get("final_scores", {})
                .get("health_literacy_score", {})
                .get("domain", None)
            )
            latest_date = latest_entry.get("date")

            return json_with_headers(
                {"user_id": user_id, "latest_update": latest_date, "health_literacy_score": hl_score},
                policy="passthrough",
            )
        except Exception as e:
            logging.error(f"[rid={getattr(request, 'request_id', '-')}] Error in get_health_literacy_diabetes: {e}")
            return api_error("internal", "Internal server error", status=500)

    return bp
