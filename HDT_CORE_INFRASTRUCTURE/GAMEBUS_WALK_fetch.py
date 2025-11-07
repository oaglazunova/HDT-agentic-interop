import requests
from HDT_CORE_INFRASTRUCTURE.GAMEBUS_WALK_parse import parse_walk_activities

def fetch_walk_data(player_id, auth_bearer):
    """
    Fetch walk activity data for a player from the GameBus API.
    """
    endpoint = f"https://api3-new.gamebus.eu/v2/players/{player_id}/activities?gds=WALK"
    headers = {"Authorization": f"Bearer {auth_bearer}"}

    try:
        response = requests.get(endpoint, headers=headers)
        response.raise_for_status()
        activities_json = response.json()
        return parse_walk_activities(activities_json)  # Parse the activities
    except requests.exceptions.RequestException as e:
        print(f"Error fetching walk data for player {player_id}: {e}")
        return []
    except Exception as e:
        print(f"Unexpected error while parsing walk data for player {player_id}: {e}")
        return []

