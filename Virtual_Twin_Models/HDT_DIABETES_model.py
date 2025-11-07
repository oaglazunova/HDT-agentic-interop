import json
import requests
from datetime import datetime
from HDT_DIABETES_calculations import *
from dotenv import load_dotenv
import os
from pytz import timezone
import pytz

# Load environment variables
load_dotenv(dotenv_path=os.path.join("config", ".env"))
MODEL_DEVELOPER_1_API_KEY = os.getenv("MODEL_DEVELOPER_1_API_KEY")

# File paths
JSON_FILE = "diabetes_pt_hl_storage.json"
API_URL_TRIVIA = "http://localhost:5000/get_trivia_data"
API_URL_SUGARVITA = "http://localhost:5000/get_sugarvita_data"

# Load JSON storage file
def load_json():
    try:
        with open(JSON_FILE, "r") as f:
            content = f.read().strip()
            if not content:
                return {"users": {}}
            return json.loads(content)
    except FileNotFoundError:
        return {"users": {}}
    except json.JSONDecodeError:
        print("Error: JSON file is corrupted or invalid.")
        return {"users": {}}


# Save JSON storage file
def save_json(data):
    with open(JSON_FILE, "w") as f:
        json.dump(data, f, indent=4)


# Fetch data from the API
def fetch_data_from_api(api_url):
    # Use Authorization header with Bearer prefix as per API documentation
    headers = {"Authorization": f"Bearer {MODEL_DEVELOPER_1_API_KEY}"}
    try:
        response = requests.get(api_url, headers=headers)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"Error fetching data from {api_url}: {e}")
        return None


# Process user data
def process_user_data(storage_data, trivia_data, sugarvita_data):
    # Convert SugarVita data to a dictionary for easier lookup
    sugarvita_dict = {user["user_id"]: user for user in sugarvita_data if "data" in user}

    for user in trivia_data:
        user_id = user["user_id"]

        # Skip if user data contains an error or is missing SugarVita data
        if "error" in user or user_id not in sugarvita_dict:
            print(f"Skipping user {user_id} due to unsupported app or missing SugarVita data.")
            continue

        # Ensure both Trivia and SugarVita data exist
        if "data" not in user or "data" not in sugarvita_dict[user_id]:
            print(f"Skipping user {user_id} due to incomplete data.")
            continue

        # Extract trivia and SugarVita metrics
        trivia_results = user["data"]["trivia_results"]
        sugarvita_results = sugarvita_dict[user_id]["data"]["sugarvita_results"]

        # Manipulate and normalize metrics
        trivia_metrics = manipulate_initial_metrics_trivia(trivia_results)
        sugarvita_pt_metrics, sugarvita_hl_metrics = manipulate_initial_metrics_sugarvita(sugarvita_results)

        # Normalize metrics
        normalized_trivia = normalize_metrics(trivia_metrics)
        normalized_sugarvita_pt = normalize_metrics(sugarvita_pt_metrics)
        normalized_sugarvita_hl = normalize_metrics(sugarvita_hl_metrics)

        # Compute scores
        trivia_score = get_health_literacy_score_trivia(normalized_trivia)
        sugarvita_score = get_health_literacy_score_sugarvita(normalized_sugarvita_hl)
        final_score = get_final_health_literacy_score(trivia_score, sugarvita_score)

        # Determine player types
        player_types = get_player_types(normalized_sugarvita_pt)

        # Prepare new entry for JSON storage
        new_entry = {
            "date": datetime.now(tz=timezone('Europe/Amsterdam')).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "final_scores": {
                "health_literacy_score": {
                    "domain": {"name": "diabetes", "score": final_score, "sources": {"trivia": trivia_score, "sugarvita": sugarvita_score}}
                },
                "player_types_labels": player_types,
            },
            "metrics_overviews": {
                "trivia": trivia_metrics,
                "sugarvita": {"pt": sugarvita_pt_metrics, "hl": sugarvita_hl_metrics},
            },
        }

        # Append new entry to the user's data in storage
        user_storage = storage_data["users"].setdefault(str(user_id), {"entries": []})
        user_storage["entries"].append(new_entry)


def main():
    # Load storage data
    storage_data = load_json()

    # Fetch trivia data
    trivia_data = fetch_data_from_api(API_URL_TRIVIA)
    if not trivia_data:
        print("Failed to fetch trivia data. Exiting.")
        return

    # Fetch SugarVita data
    sugarvita_data = fetch_data_from_api(API_URL_SUGARVITA)
    if not sugarvita_data:
        print("Failed to fetch SugarVita data. Exiting.")
        return

    # Process user data
    process_user_data(storage_data, trivia_data, sugarvita_data)

    # Save updated storage data
    save_json(storage_data)
    print("User data successfully processed and saved.")


if __name__ == "__main__":
    main()
