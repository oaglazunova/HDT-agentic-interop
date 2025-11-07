from flask import Flask, jsonify, request, send_from_directory
import json
import sys
import os, logging
from datetime import date, timedelta

# Add the project root to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Try both import styles to support running as a module or directly
try:
    # When run as a module
    from HDT_CORE_INFRASTRUCTURE.GAMEBUS_DIABETES_fetch import fetch_trivia_data, fetch_sugarvita_data
    from HDT_CORE_INFRASTRUCTURE.GAMEBUS_WALK_fetch import fetch_walk_data
    from HDT_CORE_INFRASTRUCTURE.GOOGLE_FIT_WALK_fetch import fetch_google_fit_walk_data
    from HDT_CORE_INFRASTRUCTURE.auth import authenticate_and_authorize
    from config.config import load_external_parties, load_user_permissions
except ImportError:
    from GAMEBUS_DIABETES_fetch import fetch_trivia_data, fetch_sugarvita_data
    from GAMEBUS_WALK_fetch import fetch_walk_data
    from GOOGLE_FIT_WALK_fetch import fetch_google_fit_walk_data
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

# Load users from config/users.json
# Use absolute path for users.json
config_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'config'))
users_file = os.path.join(config_dir, 'users.json')

try:
    with open(users_file) as f:
        users_data = json.load(f)
        if "users" not in users_data:
            raise ValueError("Invalid users.json format: missing 'users' key")
        users = {user["user_id"]: user for user in users_data["users"]}
    app.logger.info("Loaded %d users", len(users))
except FileNotFoundError:
    app.logger.error(f"Users file not found: {users_file}")
    users = {}
except json.JSONDecodeError as e:
    app.logger.error(f"Invalid JSON in users file: {e}")
    users = {}
except (KeyError, ValueError) as e:
    app.logger.error(f"Error loading users: {e}")
    users = {}

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
    Retrieve the connected application, player ID, and auth bearer token for a specific type of data.

    Args:
        user_id (int): The ID of the user.
        app_type (str): The type of connected app data (e.g., "diabetes_data", "walk_data").

    Returns:
        tuple: (connected_application, player_id, auth_bearer) or ("Unknown", None, None) if not found.
    """
    user = users.get(user_id)
    if not user:
        return "Unknown", None, None

    connected_apps_key = f"connected_apps_{app_type}"
    if connected_apps_key in user and user[connected_apps_key]:
        app_data = user[connected_apps_key][0]  # Assuming the first app is primary
        return app_data["connected_application"], app_data["player_id"], app_data["auth_bearer"]

    return "Unknown", None, None


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
                            "date": "string (YYYY-MM-DD HH:MM:SS)",
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

    return jsonify(metadata), 200


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

    return jsonify(metadata), 200



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

        return jsonify(response_data), 200
    except Exception as e:
        logging.error(f"Error in get_trivia_data endpoint: {e}")
        return jsonify({"error": "Internal server error"}), 500


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

        return jsonify(response_data), 200
    except Exception as e:
        logging.error(f"Error in get_sugarvita_data endpoint: {e}")
        return jsonify({"error": "Internal server error"}), 500


# Walk endpoint
@app.route("/get_walk_data", methods=["GET"])
@authenticate_and_authorize(external_parties, user_permissions, "get_walk_data")
def get_walk():
    try:
        # 1) Use IDs computed by the auth decorator; fall back to helper if needed
        client = getattr(request, "client", {}) or {}
        accessible_user_ids = getattr(request, "accessible_user_ids", None)
        if accessible_user_ids is None:
            client_id = client.get("client_id")
            accessible_user_ids = get_users_by_permission(client_id, "get_walk_data")

        # 2) Optional ?user_id= filter (and permission check)
        target_ids = list(accessible_user_ids)  # copy
        user_id_param = request.args.get("user_id")
        if user_id_param:
            try:
                uid = int(user_id_param)
            except ValueError:
                return jsonify({"error": "user_id must be an integer"}), 400
            if uid not in target_ids:
                return jsonify({"error": f"user {uid} not permitted"}), 403
            target_ids = [uid]

        # 3) Fetch per user based on connected provider
        response_data = []
        for uid in target_ids:
            app_name, player_id, auth_bearer = get_connected_app_info(uid, "walk_data")
            app_norm = (app_name or "").strip().lower()

            data = None
            if app_norm == "gamebus":
                data = fetch_walk_data(player_id, auth_bearer=auth_bearer)
            elif app_norm in ("google fit", "googlefit", "google_fit"):
                data = fetch_google_fit_walk_data(player_id, auth_bearer)
            elif app_norm.startswith("placeholder"):
                # 4) Optional mock for demos (enable with HDT_ALLOW_PLACEHOLDER_MOCKS=1)
                if os.getenv("HDT_ALLOW_PLACEHOLDER_MOCKS", "0").lower() in ("1", "true", "yes"):
                    today = date.today()
                    data = [
                        {"date": (today - timedelta(days=2)).isoformat(), "steps": 4231},
                        {"date": (today - timedelta(days=1)).isoformat(), "steps": 6120},
                        {"date": today.isoformat(),                        "steps": 3580},
                    ]
                else:
                    response_data.append({"user_id": uid, "error": f"Support for '{app_name}' is not yet implemented."})
                    continue
            else:
                response_data.append({"user_id": uid, "error": f"User {uid} does not have a connected walk application."})
                continue

            if data:
                response_data.append({"user_id": uid, "data": data})
            else:
                response_data.append({"user_id": uid, "error": f"No data found for user {uid}"})

        return jsonify(response_data), 200

    except Exception as e:
        logging.exception("Error in get_walk endpoint")  # full traceback
        return jsonify({"error": "Internal server error"}), 500



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
            return jsonify({"error": "Unauthorized access to this user's data"}), 403

        # Load diabetes_pt_hl_storage.json
        try:
            storage_file = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', "diabetes_pt_hl_storage.json"))
            with open(storage_file, "r") as f:
                storage_data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logging.error(f"Error loading diabetes_pt_hl_storage.json: {e}")
            return jsonify({"error": "Internal server error"}), 500

        # Retrieve the user data
        user_data = storage_data.get("users", {}).get(str(user_id), {})
        if not user_data:
            return jsonify({"error": f"No data found for user {user_id}"}), 404

        # Check if entries exist
        if not user_data.get("entries"):
            return jsonify({
                "user_id": user_id,
                "latest_update": None,
                "player_types": {}
            }), 200

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

        return jsonify(response), 200
    except Exception as e:
        logging.error(f"Error in get_sugarvita_player_types endpoint: {e}")
        return jsonify({"error": "Internal server error"}), 500


# Endpoint for app developers to retrieve the diabetes related health literacy scores of a user
@app.route("/get_health_literacy_diabetes", methods=["GET"])
@authenticate_and_authorize(external_parties, user_permissions, "get_health_literacy_diabetes")
def get_health_literacy_diabetes():
    try:
        # Extract user_id from query parameters
        user_id = request.args.get("user_id", type=int)

        if user_id not in request.accessible_user_ids:
            logging.debug(f"Unauthorized access attempt to health literacy for user {user_id}.")
            return jsonify({"error": "Unauthorized access to this user's data"}), 403

        # Load diabetes_pt_hl_storage.json
        try:
            storage_file = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', "diabetes_pt_hl_storage.json"))
            with open(storage_file, "r") as f:
                storage_data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logging.error(f"Error loading diabetes_pt_hl_storage.json: {e}")
            return jsonify({"error": "Internal server error"}), 500

        # Retrieve the user data
        user_data = storage_data.get("users", {}).get(str(user_id), {})
        if not user_data:
            return jsonify({"error": f"No data found for user {user_id}"}), 404

        # Check if entries exist
        if not user_data.get("entries"):
            return jsonify({
                "user_id": user_id,
                "latest_update": None,
                "health_literacy_score": None
            }), 200

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

        return jsonify(response), 200
    except Exception as e:
        logging.error(f"Error in get_health_literacy_diabetes endpoint: {e}")
        return jsonify({"error": "Internal server error"}), 500



# Root endpoint to serve the index.html file
@app.route('/')
def index():
    """
    Serve the index.html file from the static directory.
    """
    return send_from_directory(static_dir, 'index.html')

if __name__ == "__main__":
    print("Starting the HDT API server on http://localhost:5000")
    print("Press Ctrl+C to stop the server")
    app.run(debug=True, host='0.0.0.0')


@app.get("/healthz")
def healthz():
    return jsonify({"status": "ok"}), 200
