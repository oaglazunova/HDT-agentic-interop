from __future__ import annotations

from flask import Blueprint

from ..http import json_with_headers


def make_metadata_blueprint() -> Blueprint:
    bp = Blueprint("metadata", __name__)

    @bp.get("/metadata/model_developer_apis")
    def metadata_model_developer_apis():
        metadata = {
            "endpoints": [
                {
                    "name": "get_trivia_data",
                    "url": "/get_trivia_data",
                    "method": "GET",
                    "description": "Retrieve trivia data for virtual twin model training.",
                    "expected_input": {"headers": {"Authorization": "Bearer <API_KEY>"}},
                    "functionality": "Fetches trivia-related metrics from connected applications for authorized users.",
                    "output": {
                        "user_id": "integer",
                        "data": {
                            "trivia_results": "list of trivia metrics",
                            "latest_activity_info": "string containing recent activity details",
                        },
                        "error": {"code": "string", "message": "string"},
                    },
                },
                {
                    "name": "get_sugarvita_data",
                    "url": "/get_sugarvita_data",
                    "method": "GET",
                    "description": "Retrieve SugarVita data for virtual twin model training.",
                    "expected_input": {"headers": {"Authorization": "Bearer <API_KEY>"}},
                    "functionality": "Fetches SugarVita game metrics from connected applications for authorized users.",
                    "output": {
                        "user_id": "integer",
                        "data": {
                            "sugarvita_results": "list of game metrics",
                            "latest_activity_info": "string containing recent activity details",
                        },
                        "error": {"code": "string", "message": "string"},
                    },
                },
                {
                    "name": "get_walk_data",
                    "url": "/get_walk_data",
                    "method": "GET",
                    "description": "Retrieve walk data for virtual twin model training.",
                    "expected_input": {"headers": {"Authorization": "Bearer <API_KEY>"}},
                    "functionality": "Fetches step count and walk-related metrics from connected applications for authorized users.",
                    "output": {
                        "user_id": "integer",
                        "records": [
                            {
                                "date": "string (YYYY-MM-DD)",
                                "steps": "integer",
                                "distance_meters": "float or None",
                                "duration": "string (HH:MM:SS) or None",
                                "kcalories": "float or None",
                            }
                        ],
                        "error": {"code": "string", "message": "string"},
                    },
                },
            ]
        }
        return json_with_headers(metadata, policy="info")

    @bp.get("/metadata/app_developer_apis")
    def metadata_app_developer_apis():
        metadata = {
            "endpoints": [
                {
                    "name": "get_sugarvita_player_types",
                    "url": "/get_sugarvita_player_types",
                    "method": "GET",
                    "description": "Retrieve player type scores based on SugarVita gameplay.",
                    "expected_input": {
                        "query_params": {"user_id": "integer (ID of the user to query)"},
                        "headers": {"Authorization": "Bearer <API_KEY>"},
                    },
                    "functionality": "Fetches player type labels and their respective scores derived from SugarVita gameplay data.",
                    "output": {
                        "user_id": "integer",
                        "latest_update": "string (ISO datetime of latest data)",
                        "player_types": {"Socializer": "float", "Competitive": "float", "Explorer": "float"},
                        "error": {"code": "string", "message": "string"},
                    },
                    "potential_use": "Use these scores to personalize game mechanics or user experience based on player type.",
                },
                {
                    "name": "get_health_literacy_diabetes",
                    "url": "/get_health_literacy_diabetes",
                    "method": "GET",
                    "description": "Retrieve health literacy scores for diabetes management.",
                    "expected_input": {
                        "query_params": {"user_id": "integer (ID of the user to query)"},
                        "headers": {"Authorization": "Bearer <API_KEY>"},
                    },
                    "functionality": "Fetches health literacy scores related to diabetes for a specific user.",
                    "output": {
                        "user_id": "integer",
                        "latest_update": "string (ISO datetime of latest data)",
                        "health_literacy_score": {
                            "name": "string (domain name, e.g., 'diabetes')",
                            "score": "float (0 to 1)",
                            "sources": {"trivia": "float", "sugarvita": "float"},
                        },
                        "error": {"code": "string", "message": "string"},
                    },
                    "potential_use": "Use these scores to assess user education or recommend personalized educational content.",
                },
            ]
        }
        return json_with_headers(metadata, policy="info")

    return bp
