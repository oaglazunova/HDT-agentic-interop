from flask import Flask, jsonify, request, send_from_directory, make_response
import json
import sys
import os, logging
from pathlib import Path
import hashlib
import uuid

REPO_ROOT = Path(__file__).resolve().parents[1]

try:
    # When running as a script with project root on sys.path
    from validation import sanitize_walk_records, ValidationError
except ImportError:
    # When running as a package module: python -m HDT_CORE_INFRASTRUCTURE.HDT_API
    from .validation import sanitize_walk_records, ValidationError

# Add the project root to the Python path (so absolute imports work when run as a script)
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

try:
    from hdt_api_utils import parse_pagination_args, paginate, set_next_link
except ImportError:
    from .hdt_api_utils import parse_pagination_args, paginate, set_next_link

try:
    # Prefer absolute when run as a script
    from hdt_api_fetchers import FetcherResult, fetch_walk_batch
except ImportError:
    # Fallback to relative when run as a module
    from .hdt_api_fetchers import FetcherResult, fetch_walk_batch


# ===== helpers ==========

def _stable_json_dumps(obj) -> str:
    # Compact + deterministic JSON (no spaces, sorted keys)
    return json.dumps(obj, separators=(",", ":"), sort_keys=True, ensure_ascii=False)

def _compute_etag(payload, *, variant: dict | None = None) -> str:
    """
    Compute a strong ETag based on the response body and a 'variant' dict.
    The variant makes the ETag safe across different clients/queries.
    """
    h = hashlib.sha256()

    # Body
    h.update(_stable_json_dumps(payload).encode("utf-8"))

    # Variant (e.g., path, query, client id, policy)
    cid = (getattr(request, "client", {}) or {}).get("client_id", "unknown")
    var = {
        "path": request.path,
        "qs": request.query_string.decode("utf-8", "ignore"),
        "client_id": cid,
    }
    if variant:
        var.update(variant)
    h.update(_stable_json_dumps(var).encode("utf-8"))

    # Strong ETag (quoted per RFC 7232)
    return f"\"{h.hexdigest()[:16]}\""

# ============================

def json_with_headers(
        payload,
        *,
        policy: str | None = None,
        redactions: int | None = None,
        status: int = 200,
        etag_variant: dict | None = None,
        extra_headers: dict[str, str] | None = None,
    ):
    """
    Return a JSON response with governance headers, plus conditional ETag/304.
    - Computes a stable ETag for 200 OK responses (optionally varied by 'etag_variant').
    - If If-None-Match matches, returns 304 with no body (still sets headers).
    - 'extra_headers' lets callers add Link / X-Limit / X-Offset / X-Total, etc.
    """
    cid = (getattr(request, "client", {}) or {}).get("client_id", "unknown")
    users_count = len(payload) if isinstance(payload, list) else 1
    req_id = getattr(request, "request_id", None)

    # Compute ETag only for cacheable 200 responses
    etag = None
    if status == 200:
        etag = _compute_etag(payload, variant=etag_variant)

        # Conditional GET handling
        inm = request.headers.get("If-None-Match")
        if inm:
            candidates = [x.strip() for x in inm.split(",")]
            if etag in candidates:
                resp = make_response("", 304)
                # Standard headers
                resp.headers["ETag"] = etag
                resp.headers["X-Client-Id"] = str(cid)
                resp.headers["X-Users-Count"] = str(users_count)
                if policy is not None:
                    resp.headers["X-Policy"] = policy
                resp.headers["X-Request-Id"] = req_id or ""
                # CORS + expose
                resp.headers["Access-Control-Allow-Origin"] = request.headers.get("Origin", "*")
                resp.headers["Vary"] = "Origin"
                resp.headers["Access-Control-Expose-Headers"] = (
                    "ETag, X-Client-Id, X-Users-Count, X-Policy, X-Request-Id, Link, X-Limit, X-Offset, X-Total"
                )

                # pagination headers (if any): carry any extra headers (e.g., pagination) on 304 too
                for k, v in (extra_headers or {}).items():
                    resp.headers[k] = v
                # cacheable 304
                resp.headers.setdefault("Cache-Control", "private, must-revalidate")
                return resp

    # Normal JSON response
    resp = jsonify(payload)
    resp.status_code = status
    resp.headers["X-Client-Id"] = str(cid)
    resp.headers["X-Users-Count"] = str(users_count)
    if policy is not None:
        resp.headers["X-Policy"] = policy
    if redactions is not None:
        resp.headers["X-Policy-Redactions"] = str(int(redactions))
    if etag:
        resp.headers["ETag"] = etag
    resp.headers["X-Request-Id"] = req_id

    # CORS + expose (include Link + paging headers)
    resp.headers["Access-Control-Allow-Origin"] = request.headers.get("Origin", "*")
    resp.headers["Vary"] = "Origin"
    resp.headers["Access-Control-Expose-Headers"] = (
        "ETag, X-Client-Id, X-Users-Count, X-Policy, X-Request-Id, Link, X-Limit, X-Offset, X-Total"
    )

    # Caller-supplied headers (Link, X-Limit/Offset/Total, etc.)
    for k, v in (extra_headers or {}).items():
        resp.headers[k] = v
    # in json_with_headers(...) for 200s only
    if status == 200:
        resp.headers.setdefault("Cache-Control", "private, must-revalidate")
    return resp


def api_error(code: str,
              message: str,
              *,
              status: int = 400,
              details: dict | None = None,
              policy: str = "error"):
    """
    Return a consistent error envelope:
    {
      "error": {"code": "<code>", "message": "<message>", "details": {...}}
    }
    …plus the same governance headers via json_with_headers().
    """
    payload = {"error": {"code": code, "message": message}}
    if details:
        payload["error"]["details"] = details
    return json_with_headers(payload, status=status, policy=policy)

# Try both import styles to support running as a module or directly
try:
    # When run as a module
    from HDT_CORE_INFRASTRUCTURE.GAMEBUS_DIABETES_fetch import fetch_trivia_data, fetch_sugarvita_data
    from HDT_CORE_INFRASTRUCTURE.auth import authenticate_and_authorize
    from config.config import load_external_parties, load_user_permissions
except ImportError:
    from GAMEBUS_DIABETES_fetch import fetch_trivia_data, fetch_sugarvita_data
    from auth import authenticate_and_authorize
    from config.config import load_external_parties, load_user_permissions

app = Flask(__name__)

 # Load configurations securely
external_parties = load_external_parties()
# Normalize shape: support {"external_parties":[...]} or just [...]
if isinstance(external_parties, dict):
    external_parties = external_parties.get("external_parties", []) or []
user_permissions = load_user_permissions()

# Helpful startup logs
logging.basicConfig(level=logging.INFO)
app.logger.info("Loaded %d external parties: %s",
                len(external_parties),
                [(p.get("client_id"), p.get("api_key")) for p in external_parties])
app.logger.info("Loaded %d user-permission entries", len(user_permissions))


# Define the path to the static directory
static_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'static'))

# ---- Users loader (public + secrets overlay) --------------------------------
config_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'config'))
USERS_PUBLIC_FILE = os.path.join(config_dir, 'users.json')
USERS_SECRETS_FILE = os.path.join(config_dir, 'users.secrets.json')

def _load_users_file(path: str) -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or "users" not in data or not isinstance(data["users"], list):
        raise ValueError(f"Invalid users file format: {path}")
    return data["users"]

def _merge_lists_by_identity(pub_list: list[dict], sec_list: list[dict], identity_keys=("connected_application","player_id")) -> list[dict]:
    """
    Merge two lists of connector entries:
    - Match items by identity_keys (connected_application + player_id).
    - If match found, overlay secret fields (e.g., auth_bearer) onto the public item.
    - If no secret match, keep the public item as-is.
    """
    merged = []
    # Build fast lookup for secrets
    sec_index = {}
    for s in sec_list or []:
        key = tuple((s.get(k) or "") for k in identity_keys)
        sec_index.setdefault(key, []).append(s)

    for p in pub_list or []:
        key = tuple((p.get(k) or "") for k in identity_keys)
        s = (sec_index.get(key) or [None])[0]
        if s:
            # Overlay – but do not let secrets change identity fields
            over = {**p, **{k: v for k, v in s.items() if k not in {"connected_application","player_id"}}}
            merged.append(over)
        else:
            merged.append(p)
    return merged

def _merge_users(public_users: list[dict], secret_users: list[dict]) -> dict[int, dict]:
    # Build secret lookup by user_id
    sec_by_uid = {int(u.get("user_id")): u for u in secret_users or [] if "user_id" in u}

    merged_by_uid: dict[int, dict] = {}
    for pu in public_users:
        uid = int(pu["user_id"])
        su = sec_by_uid.get(uid, {})
        merged_entry = dict(pu)  # shallow copy

        # Merge all known connector arrays you use in code
        for key in ("connected_apps_diabetes_data", "connected_apps_walk_data", "connected_apps_nutrition_data"):
            merged_entry[key] = _merge_lists_by_identity(
                pu.get(key, []),
                (su or {}).get(key, [])
            )
        merged_by_uid[uid] = merged_entry

    return merged_by_uid

try:
    public = _load_users_file(USERS_PUBLIC_FILE)
except FileNotFoundError:
    app.logger.error("Users public file not found: %s", USERS_PUBLIC_FILE)
    public = []
except Exception as e:
    app.logger.error("Error loading users.json: %s", e)
    public = []

try:
    secrets = _load_users_file(USERS_SECRETS_FILE)
    app.logger.info("Loaded users.secrets.json (overlay)")
except FileNotFoundError:
    secrets = []
    app.logger.warning("users.secrets.json not found; proceeding without secrets overlay")
except Exception as e:
    secrets = []
    app.logger.error("Error loading users.secrets.json: %s", e)

users = _merge_users(public, secrets)
app.logger.info("Loaded %d users (merged)", len(users))

def get_users_by_permission(client_id, required_permission):
    """
    Identify users who have granted the requesting client access to the required permission.
    """
    accessible_users = []
    for user_id, permissions in (user_permissions or {}).items():
        allowed = permissions.get("allowed_clients", {})
        if client_id in allowed and required_permission in allowed[client_id]:
            try:
                accessible_users.append(int(user_id))
            except (ValueError, TypeError):
                app.logger.warning(f"Invalid user_id format: {user_id}")
    return accessible_users



def get_connected_app_info(user_id, app_type):
    """
    Return (connected_application, player_id, auth_bearer) or ("Unknown", None, None).
    Reads from the merged in-memory 'users' dict.
    """
    user = users.get(user_id)
    if not user:
        return "Unknown", None, None

    connected_apps_key = f"connected_apps_{app_type}"
    entries = user.get(connected_apps_key) or []
    if not entries:
        return "Unknown", None, None

    app_data = entries[0]  # first connector is primary
    return (
        app_data.get("connected_application", "Unknown"),
        app_data.get("player_id"),
        app_data.get("auth_bearer")  # may be None if secrets missing—fetchers should handle that
    )

# Metadata Endpoint for Model Developer APIs
@app.route("/metadata/model_developer_apis", methods=["GET"])
def metadata_model_developer_apis():
    """
    Provide metadata for model developer APIs.
    """
    metadata = {
        "endpoints": [
            {
                "name": "get_trivia_data",
                "url": "/get_trivia_data",
                "method": "GET",
                "description": "Retrieve trivia data for virtual twin model training.",
                "expected_input": {
                    "headers": {
                        "Authorization": "Bearer <API_KEY>"
                    }
                },
                "functionality": "Fetches trivia-related metrics from connected applications for authorized users.",
                "output": {
                    "user_id": "integer",
                    "data": {
                        "trivia_results": "list of trivia metrics",
                        "latest_activity_info": "string containing recent activity details"
                    },
                    "error": "Error message if something goes wrong."
                }
            },
            {
                "name": "get_sugarvita_data",
                "url": "/get_sugarvita_data",
                "method": "GET",
                "description": "Retrieve SugarVita data for virtual twin model training.",
                "expected_input": {
                    "headers": {
                        "Authorization": "Bearer <API_KEY>"
                    }
                },
                "functionality": "Fetches SugarVita game metrics from connected applications for authorized users.",
                "output": {
                    "user_id": "integer",
                    "data": {
                        "sugarvita_results": "list of game metrics",
                        "latest_activity_info": "string containing recent activity details"
                    },
                    "error": "Error message if something goes wrong."
                }
            },
            {
                "name": "get_walk_data",
                "url": "/get_walk_data",
                "method": "GET",
                "description": "Retrieve walk data for virtual twin model training.",
                "expected_input": {
                    "headers": {
                        "Authorization": "Bearer <API_KEY>"
                    }
                },
                "functionality": "Fetches step count and walk-related metrics from connected applications for authorized users.",
                "output": {
                    "user_id": "integer",
                    "data": [
                        {
                            "date": "string (YYYY-MM-DD)",
                            "steps": "integer",
                            "distance_meters": "float or None",
                            "duration": "string (HH:MM:SS) or None",
                            "kcalories": "float or None"
                        }
                    ],
                    "error": "Error message if something goes wrong."
                }
            }
        ]
    }

    return json_with_headers(metadata, policy="info")


# Metadata Endpoint for App Developer APIs
@app.route("/metadata/app_developer_apis", methods=["GET"])
def metadata_app_developer_apis():
    """
    Provide metadata for app developer APIs.
    """
    metadata = {
        "endpoints": [
            {
                "name": "get_sugarvita_player_types",
                "url": "/get_sugarvita_player_types",
                "method": "GET",
                "description": "Retrieve player type scores based on SugarVita gameplay.",
                "expected_input": {
                    "query_params": {
                        "user_id": "integer (ID of the user to query)"
                    },
                    "headers": {
                        "Authorization": "Bearer <API_KEY>"
                    }
                },
                "functionality": "Fetches player type labels and their respective scores derived from SugarVita gameplay data.",
                "output": {
                    "user_id": "integer",
                    "latest_update": "string (ISO datetime of latest data)",
                    "player_types": {
                        "Socializer": "float",
                        "Competitive": "float",
                        "Explorer": "float"
                    },
                    "error": "Error message if something goes wrong."
                },
                "potential_use": "Use these scores to personalize game mechanics or user experience based on player type."
            },
            {
                "name": "get_health_literacy_diabetes",
                "url": "/get_health_literacy_diabetes",
                "method": "GET",
                "description": "Retrieve health literacy scores for diabetes management.",
                "expected_input": {
                    "query_params": {
                        "user_id": "integer (ID of the user to query)"
                    },
                    "headers": {
                        "Authorization": "Bearer <API_KEY>"
                    }
                },
                "functionality": "Fetches health literacy scores related to diabetes for a specific user.",
                "output": {
                    "user_id": "integer",
                    "latest_update": "string (ISO datetime of latest data)",
                    "health_literacy_score": {
                        "name": "string (domain name, e.g., 'diabetes')",
                        "score": "float (0 to 1)",
                        "sources": {
                            "trivia": "float",
                            "sugarvita": "float"
                        }
                    },
                    "error": "Error message if something goes wrong."
                },
                "potential_use": "Use these scores to assess user education or recommend personalized educational content."
            }
        ]
    }

    return json_with_headers(metadata, policy="info")

@app.route("/openapi.json", methods=["GET"])
def openapi():
    """
    Serve the OpenAPI specification. Prefer the repository file at `openapi/openapi.json`
    to ensure it stays in sync with docs, and fallback to a minimal in-code spec if the
    file isn't available.
    """
    try:
        repo_root = Path(__file__).resolve().parents[1]
        spec_path = repo_root / "openapi" / "openapi.json"
        with spec_path.open("r", encoding="utf-8") as f:
            spec = json.load(f)
        return json_with_headers(spec, policy="info")
    except Exception:
        # Minimal fallback spec that still contains the headers/components expected by tests
        spec = {
            "openapi": "3.0.3",
            "info": {"title": "HDT API", "version": "0.1.0"},
            "paths": {
                "/get_walk_data": {
                    "get": {
                        "summary": "Walk data (paginated for single-user)",
                        "parameters": [
                            {"name": "user_id", "in": "query", "schema": {"type": "integer"}},
                            {"name": "limit", "in": "query", "schema": {"type": "integer", "minimum": 1, "maximum": 1000}},
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
                                            "oneOf": [
                                                {"$ref": "#/components/schemas/UserStreamEnvelope"},
                                                {"type": "array", "items": {"$ref": "#/components/schemas/UserStreamEnvelope"}},
                                            ]
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
                            "data": {"type": "array", "items": {"$ref": "#/components/schemas/WalkRecord"}},
                            "page": {"$ref": "#/components/schemas/Page"},
                        },
                        "required": ["user_id", "data"],
                    },
                },
            },
        }
        return json_with_headers(spec, policy="info")


# Below are the API endpoints that virtual twin model developers can call to retrieve user data for specific domains (e.g., trivia, SugarVita, walking).
#
# The functionality of these endpoints includes:
# 1. **Permission Validation**:
#    - Determine which users have authorized the querying model developer to access their data based on user permissions stored in user_permissions.json.
#    - Use the authenticate_and_authorize decorator to validate external parties and permissions for the querying client.
#
# 2. **Connected Application Retrieval**:
#    - For each authorized user, retrieve the relevant connected application, player_id, and auth_bearer token using the get_connected_app_info() function.
#    - The connected app determines the source of data (e.g., GameBus or Placeholder apps).
#
# 3. **Data Fetching**:
#    - Call the appropriate fetch function (e.g., fetch_trivia_data, fetch_sugarvita_data, fetch_walk_data) to query the external application.
#    - Fetch and preprocess the raw data using external application-specific logic.
#
# 4. **Error Handling**:
#    - Handle unsupported applications or missing configurations gracefully by providing clear error messages in the response.
#
# 5. **Response Aggregation**:
#    - Aggregate and structure the data for all authorized users and return it as a JSON response to the querying client.
#
# Each endpoint is tailored for a specific domain (e.g., trivia, SugarVita, walking), leveraging the flexibility and modularity of the system architecture.

# Trivia endpoint
@app.route("/get_trivia_data", methods=["GET"])
@authenticate_and_authorize(external_parties, user_permissions, "get_trivia_data")
def get_trivia_data():
    try:
        client_id = request.client["client_id"]
        accessible_user_ids = get_users_by_permission(client_id, "get_trivia_data")
        response_data = []

        for user_id in accessible_user_ids:
            app_name, player_id, auth_bearer = get_connected_app_info(user_id, "diabetes_data")

            if app_name == "GameBus":
                data, latest_activity_info = fetch_trivia_data(player_id, auth_bearer=auth_bearer)
                if data:
                    response_data.append({
                        "user_id": user_id,
                        "data": {
                            "trivia_results": data,
                            "latest_activity_info": latest_activity_info
                        }
                    })
                else:
                    response_data.append({"user_id": user_id, "error": f"No data found for user {user_id}"})
            elif app_name == "Placeholder diabetes app":
                response_data.append({"user_id": user_id, "error": f"Support for '{app_name}' is not yet implemented."})
            else:
                response_data.append({"user_id": user_id, "error": f"User {user_id} does not have a connected diabetes application."})

        return json_with_headers(response_data, policy="passthrough")
    except Exception as e:
        logging.error(f"[rid={getattr(request, 'request_id', '-')}] Error in get_trivia_data: {e}")
        return api_error("internal", "Internal server error", status=500)


# SugarVita endpoint
@app.route("/get_sugarvita_data", methods=["GET"])
@authenticate_and_authorize(external_parties, user_permissions, "get_sugarvita_data")
def get_sugarvita_data():
    try:
        client_id = request.client["client_id"]
        accessible_user_ids = get_users_by_permission(client_id, "get_sugarvita_data")
        response_data = []

        for user_id in accessible_user_ids:
            app_name, player_id, auth_bearer = get_connected_app_info(user_id, "diabetes_data")

            if app_name == "GameBus":
                data, latest_activity_info = fetch_sugarvita_data(player_id, auth_bearer=auth_bearer)
                if data:
                    response_data.append({
                        "user_id": user_id,
                        "data": {
                            "sugarvita_results": data,
                            "latest_activity_info": latest_activity_info
                        }
                    })
                else:
                    response_data.append({"user_id": user_id, "error": f"No data found for user {user_id}"})
            elif app_name == "Placeholder diabetes app":
                response_data.append({"user_id": user_id, "error": f"Support for '{app_name}' is not yet implemented."})
            else:
                response_data.append({"user_id": user_id, "error": f"User {user_id} does not have a connected diabetes application."})

        return json_with_headers(response_data, policy="passthrough")
    except Exception as e:
        logging.error(f"[rid={getattr(request, 'request_id', '-')}] Error in get_sugarvita_data: {e}")
        return api_error("internal", "Internal server error", status=500)


# Walk endpoint
@app.route("/get_walk_data", methods=["GET"])
@authenticate_and_authorize(external_parties, user_permissions, "get_walk_data")
def get_walk():
    try:
        # decorator computes request.accessible_user_ids
        accessible_user_ids = getattr(request, "accessible_user_ids", [])
        user_id = request.args.get("user_id", type=int)

        # Common pagination once (applies to single- and multi-user paths)
        limit, offset, err = parse_pagination_args()
        if err:
            msg, code = err
            return json_with_headers({"error": msg}, status=code, policy="error")

        # -------- Single-user (explicit ?user_id=...) ----------
        if user_id is not None:
            if user_id not in accessible_user_ids:
                return api_error("forbidden", f"User {user_id} not permitted", status=403, policy="deny")

            res = fetch_walk_batch(user_id, limit, offset)  # -> {"records": [...], "total": int|None}
            try:
                cleaned = sanitize_walk_records(res.get("records", []))  # strict validation
            except ValidationError as e:
                return api_error("bad_input", str(e), status=400)

            page, has_next = paginate(res.get("total"), limit, offset)

            payload = {"user_id": user_id, "data": cleaned, "page": page}
            extra = {"X-Limit": str(page.get("limit", "")), "X-Offset": str(page.get("offset", ""))}
            if page.get("total") is not None:
                extra["X-Total"] = str(page["total"])

            resp = json_with_headers(
                payload,
                policy="passthrough",
                extra_headers=extra,
                etag_variant={"policy": "passthrough", "user_id": user_id, "limit": limit, "offset": offset},
            )
            if has_next:
                resp = set_next_link(resp, request.base_url, limit, offset + limit)
            return resp

        # -------- Multi-user (no ?user_id=... provided) ----------
        envelopes = []
        any_has_next = False

        for uid in accessible_user_ids:
            res = fetch_walk_batch(uid, limit, offset)
            try:
                cleaned = sanitize_walk_records(res.get("records", []))
            except ValidationError as e:
                # Keep the envelope, but mark as error for that uid
                envelopes.append({"user_id": uid, "error": f"bad_input: {e}"})
                continue

            page, has_next = paginate(res.get("total"), limit, offset)
            any_has_next = any_has_next or has_next
            envelopes.append({"user_id": uid, "data": cleaned, "page": page})

        resp = json_with_headers(
            envelopes,
            policy="passthrough",
            etag_variant={"policy": "passthrough", "limit": limit, "offset": offset},
        )
        if any_has_next:
            resp = set_next_link(resp, request.base_url, limit, offset + limit)
        return resp

    except Exception:
        logging.exception(f"[rid={getattr(request, 'request_id', '-')}] Error in get_walk_data")
        return api_error("internal", "Internal server error", status=500)



# Below are endpoints that health app developers can use to obtain insights about its users via the virtual twin

# Endpoint for app developers to retrieve the sugarvita player type scores of a user
@app.route("/get_sugarvita_player_types", methods=["GET"])
@authenticate_and_authorize(external_parties, user_permissions, "get_sugarvita_player_types")
def get_sugarvita_player_types():
    try:
        # Extract user_id from query parameters
        user_id = request.args.get("user_id", type=int)

        if user_id not in request.accessible_user_ids:
            logging.debug(f"Unauthorized access attempt to player types for user {user_id}.")
            return api_error("forbidden", "Unauthorized access to this user's data", status=403, policy="deny")

        # Load diabetes_pt_hl_storage.json
        try:
            storage_file = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', "diabetes_pt_hl_storage.json"))
            with open(storage_file, "r") as f:
                storage_data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logging.error(f"[rid={getattr(request, 'request_id', '-')}] Error loading diabetes_pt_hl_storage.json: {e}")
            return api_error("internal", "Internal server error", status=500)

        # Retrieve the user data
        user_data = storage_data.get("users", {}).get(str(user_id), {})
        if not user_data:
            return api_error("not_found", f"No data found for user {user_id}", status=404)

        # Check if entries exist
        if not user_data.get("entries"):
            return json_with_headers({
                "user_id": user_id,
                "latest_update": None,
                "player_types": {}
            }, policy="passthrough")

        # Get the latest entry
        latest_entry = user_data["entries"][-1]
        player_types_labels = latest_entry.get("final_scores", {}).get("player_types_labels", {})
        latest_date = latest_entry.get("date")

        # Prepare the response
        response = {
            "user_id": user_id,
            "latest_update": latest_date,
            "player_types": player_types_labels
        }

        return json_with_headers(response, policy="passthrough")
    except Exception as e:
        logging.error(f"[rid={getattr(request, 'request_id', '-')}] Error in get_sugarvita_player_types: {e}")
        return json_with_headers({"error": "Internal server error"}, status=500, policy="error")
        #return json_with_headers({"error": f"No data found for user {user_id}"}, status=404, policy="error")
        #return json_with_headers({"error": "Unauthorized access to this user's data"}, status=403, policy="deny")


# Endpoint for app developers to retrieve the diabetes related health literacy scores of a user
@app.route("/get_health_literacy_diabetes", methods=["GET"])
@authenticate_and_authorize(external_parties, user_permissions, "get_health_literacy_diabetes")
def get_health_literacy_diabetes():
    try:
        # Extract user_id from query parameters
        user_id = request.args.get("user_id", type=int)

        if user_id not in request.accessible_user_ids:
            logging.debug(f"Unauthorized access attempt to health literacy for user {user_id}.")
            return api_error("forbidden", "Unauthorized access to this user's data", status=403, policy="deny")

        # Load diabetes_pt_hl_storage.json
        try:
            storage_file = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', "diabetes_pt_hl_storage.json"))
            with open(storage_file, "r") as f:
                storage_data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logging.error(f"[rid={getattr(request, 'request_id', '-')}] Error loading diabetes_pt_hl_storage.json: {e}")
            return api_error("internal", "Internal server error", status=500)

        # Retrieve the user data
        user_data = storage_data.get("users", {}).get(str(user_id), {})
        if not user_data:
            return api_error("not_found", f"No data found for user {user_id}", status=404)

        # Check if entries exist
        if not user_data.get("entries"):
            return json_with_headers({
                "user_id": user_id,
                "latest_update": None,
                "health_literacy_score": None
            }, policy="passthrough")

        # Get the latest entry
        latest_entry = user_data["entries"][-1]
        health_literacy_score = latest_entry.get("final_scores", {}).get("health_literacy_score", {}).get("domain", None)
        latest_date = latest_entry.get("date")

        # Prepare the response
        response = {
            "user_id": user_id,
            "latest_update": latest_date,
            "health_literacy_score": health_literacy_score
        }

        return json_with_headers(response, policy="passthrough")
    except Exception as e:
        logging.error(f"[rid={getattr(request, 'request_id', '-')}] Error in get_health_literacy_diabetes: {e}")
        return json_with_headers({"error": "Internal server error"}, status=500, policy="error")
        #return json_with_headers({"error": f"No data found for user {user_id}"}, status=404, policy="error")
        #return json_with_headers({"error": "Unauthorized access to this user's data"}, status=403, policy="deny")

def serve_stream_single_user(*, user_id: int, fetch_batch, policy_label: str):
    limit, offset, err = parse_pagination_args()
    if err:
        msg, code = err
        return json_with_headers({"error": msg}, status=code, policy="error")

    res = fetch_batch(user_id, limit, offset)  # {"records": [...], "total": int|None}
    try:
        cleaned = sanitize_walk_records(res.get("records", []))  # strict by default
    except ValidationError as e:
        return api_error("bad_input", str(e), status=400)

    page, has_next = paginate(
        res.get("total"), limit, offset,
        returned_count=len(cleaned)  # helps the has_next heuristic when total=None
    )

    payload = {"user_id": user_id, "data": cleaned, "page": page}
    extra = {"X-Limit": str(page.get("limit","")), "X-Offset": str(page.get("offset",""))}
    if page.get("total") is not None:
        extra["X-Total"] = str(page["total"])  # keep as string for headers

    resp = json_with_headers(
        payload,
        policy=policy_label,
        extra_headers=extra,
        etag_variant={"policy": policy_label}
    )
    if has_next:
        base = request.base_url
        resp = set_next_link(resp, base, limit, offset + limit)
    return resp


# Root endpoint to serve the index.html file
@app.route('/')
def index():
    """
    Serve the index.html file from the static directory.
    """
    return send_from_directory(static_dir, 'index.html')

@app.route("/openapi.yaml")
def openapi_yaml():
    # Serve the OpenAPI file from the repo root
    return send_from_directory(str(REPO_ROOT), "openapi.yaml", mimetype="text/yaml")

@app.route("/docs")
def api_docs():
    # Serve Redoc HTML that points at /openapi.yaml
    return send_from_directory(static_dir, "docs/index.html")

@app.get("/healthz")
def healthz():
    return json_with_headers({"status": "ok"}, policy="info")

# tiny dev-only debug endpoint
@app.get("/__debug/effective_user/<int:user_id>")
def debug_effective_user(user_id: int):
    if os.getenv("DEBUG_USERS", "0") not in ("1","true","yes"):
        return api_error("disabled", "Debug endpoint is disabled", status=404, policy="info")
    u = users.get(user_id)
    return json_with_headers(u or {}, policy="info")

# Correlation IDs: accept incoming or generate a new one
@app.before_request
def ensure_request_id():
    rid = (
        request.headers.get("X-Request-Id")
        or request.headers.get("X-Correlation-Id")
        or uuid.uuid4().hex
    )
    setattr(request, "request_id", rid)

#If run from a browser
@app.after_request
def add_cors_headers(resp):
    # CORS headers for all responses
    resp.headers.setdefault("Access-Control-Allow-Methods", "GET,OPTIONS")
    resp.headers.setdefault(
        "Access-Control-Allow-Headers",
        "Authorization, X-API-KEY, Content-Type, If-None-Match, X-Request-Id, X-Correlation-Id"
    )
    # Ensure X-Request-Id is always present (even for OPTIONS or non-JSON responses)
    rid = getattr(request, "request_id", None)
    if rid and "X-Request-Id" not in resp.headers:
        resp.headers["X-Request-Id"] = rid
    # Also expose it if a handler forgot
    resp.headers.setdefault(
        "Access-Control-Expose-Headers",
        "ETag, X-Client-Id, X-Users-Count, X-Policy, X-Request-Id, Link, X-Limit, X-Offset, X-Total"
    )
    return resp

#If run from a browser
@app.route("/<path:_any>", methods=["OPTIONS"])
def any_options(_any):
    # Minimal OK for preflight
    return ("", 204)

if __name__ == "__main__":
    print("Starting the HDT API server on http://localhost:5000")
    print("Press Ctrl+C to stop the server")
    app.run(debug=True, host='0.0.0.0')



