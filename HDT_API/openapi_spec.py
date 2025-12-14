from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


def load_openapi_spec(repo_root: Path) -> Dict[str, Any]:
    """Load and return the OpenAPI spec as a Python dict.

    Canonical source: repo_root/openapi.yaml.
    Fallback: repo_root/openapi/openapi.json.
    Final fallback: minimal spec used by tests.
    """

    yaml_path = repo_root / "openapi.yaml"
    json_path = repo_root / "openapi" / "openapi.json"

    # Prefer canonical YAML
    try:
        try:
            import yaml  # type: ignore
        except Exception:
            yaml = None  # type: ignore

        if yaml is not None and yaml_path.exists():
            with yaml_path.open("r", encoding="utf-8") as f:
                spec = yaml.safe_load(f)
            if isinstance(spec, dict):
                return spec
    except Exception:
        pass

    # Fallback: pre-generated JSON
    try:
        if json_path.exists():
            with json_path.open("r", encoding="utf-8") as f:
                spec = json.load(f)
            if isinstance(spec, dict):
                return spec
    except Exception:
        pass

    # Minimal fallback
    return {
        "openapi": "3.0.3",
        "info": {"title": "HDT API", "version": "0.1.0"},
        "paths": {
            "/get_walk_data": {
                "get": {
                    "summary": "Walk data (always array of user envelopes)",
                    "description": (
                        "Always returns an array of per-user envelopes. If `user_id` is provided, the response is a "
                        "1-element array. Without `user_id`, returns envelopes for all users the client is authorized "
                        "to access."
                    ),
                    "parameters": [
                        {"name": "user_id", "in": "query", "schema": {"type": "integer"}},
                        {
                            "name": "limit",
                            "in": "query",
                            "schema": {"type": "integer", "minimum": 1, "maximum": 1000},
                        },
                        {"name": "offset", "in": "query", "schema": {"type": "integer", "minimum": 0}},
                    ],
                    "responses": {
                        "200": {
                            "description": "OK",
                            "headers": {
                                "ETag": {"schema": {"type": "string"}},
                                "X-Request-Id": {"schema": {"type": "string"}},
                                "Link": {"schema": {"type": "string"}},
                                "X-Limit": {"schema": {"type": "integer"}},
                                "X-Offset": {"schema": {"type": "integer"}},
                                "X-Total": {"schema": {"type": "integer"}},
                            },
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "array",
                                        "items": {"$ref": "#/components/schemas/UserStreamEnvelope"},
                                    }
                                }
                            },
                        },
                        "304": {"description": "Not Modified (ETag match)."},
                    },
                }
            }
        },
        "components": {
            "headers": {
                "ETag": {"schema": {"type": "string"}},
                "X-Request-Id": {"schema": {"type": "string"}},
                "X-Client-Id": {"schema": {"type": "string"}},
                "X-Users-Count": {"schema": {"type": "integer"}},
                "X-Policy": {"schema": {"type": "string"}},
                "Link": {"schema": {"type": "string"}},
                "X-Limit": {"schema": {"type": "integer"}},
                "X-Offset": {"schema": {"type": "integer"}},
                "X-Total": {"schema": {"type": "integer"}},
            },
            "schemas": {
                "ErrorObject": {
                    "type": "object",
                    "properties": {
                        "code": {"type": "string"},
                        "message": {"type": "string"},
                        "details": {"type": "object", "additionalProperties": True},
                    },
                    "required": ["code", "message"],
                },
                "WalkRecord": {
                    "type": "object",
                    "properties": {
                        "date": {"type": "string", "format": "date"},
                        "steps": {"type": "integer"},
                        "distance_meters": {"type": ["number", "null"]},
                        "duration": {"type": ["string", "null"]},
                        "kcalories": {"type": ["number", "null"]},
                    },
                },
                "Page": {
                    "type": "object",
                    "properties": {
                        "total": {"type": "integer"},
                        "limit": {"type": "integer"},
                        "offset": {"type": "integer"},
                    },
                    "required": ["total", "limit", "offset"],
                },
                "UserStreamEnvelope": {
                    "type": "object",
                    "properties": {
                        "user_id": {"type": "integer"},
                        "records": {
                            "type": "array",
                            "items": {"$ref": "#/components/schemas/WalkRecord"},
                        },
                        "page": {"$ref": "#/components/schemas/Page"},
                        "error": {
                            "anyOf": [
                                {"$ref": "#/components/schemas/ErrorObject"},
                                {"type": "null"},
                            ]
                        },
                    },
                    "description": "Either `records`+`page` are present or an `error` object.",
                    "anyOf": [
                        {"required": ["user_id", "records", "page"]},
                        {"required": ["user_id", "error"]},
                    ],
                },
            },
        },
    }
