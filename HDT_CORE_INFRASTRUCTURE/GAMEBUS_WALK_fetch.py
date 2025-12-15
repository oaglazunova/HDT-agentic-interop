import logging
import requests
from HDT_CORE_INFRASTRUCTURE.GAMEBUS_WALK_parse import parse_walk_activities

logger = logging.getLogger(__name__)

def fetch_walk_data(player_id, auth_bearer):
    endpoint = f"https://api3-new.gamebus.eu/v2/players/{player_id}/activities?gds=WALK"
    headers = {"Authorization": f"Bearer {auth_bearer}"}

    try:
        response = requests.get(endpoint, headers=headers)
        response.raise_for_status()
        activities_json = response.json()
        return parse_walk_activities(activities_json)
    except requests.exceptions.RequestException as e:
        logger.error("Error fetching walk data for player %s: %s", player_id, e)
        return None
    except Exception as e:
        logger.exception("Unexpected error while parsing walk data for player %s: %s", player_id, e)
        return None
