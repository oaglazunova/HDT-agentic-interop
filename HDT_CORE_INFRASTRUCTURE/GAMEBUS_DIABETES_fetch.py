import requests
import logging
from datetime import datetime
from HDT_CORE_INFRASTRUCTURE.GAMEBUS_DIABETES_parse import parse_json_trivia, parse_json_sugarvita

logger = logging.getLogger(__name__)

def format_date_to_dd_mm_yyyy(date_str):
    """
    Converts an ISO 8601 date string to DD-MM-YYYY format that the GameBus API expects.
    """
    try:
        return datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%SZ").strftime("%d-%m-%Y")
    except ValueError:
        logger.warning(f"Invalid date format: {date_str}. Skipping conversion.")
        return None

def fetch_trivia_data(player_id, start_date=None, end_date=None, auth_bearer=None):
    """
    Fetches trivia data for a player based on date range with proper authorization.
    """
    logger.info(f"Fetching trivia data for player {player_id}")

    # Convert dates to DD-MM-YYYY format that the GameBus API expects
    start_date = format_date_to_dd_mm_yyyy(start_date) if start_date else None
    end_date = format_date_to_dd_mm_yyyy(end_date) if end_date else None

    endpoint = f"https://api3-new.gamebus.eu/v2/players/{player_id}/activities?gds=ANSWER_TRIVIA_DIABETES"

    if start_date:
        endpoint += f"&start={start_date}"
    if end_date:
        endpoint += f"&end={end_date}"

    headers = {"Authorization": f"Bearer {auth_bearer}"}

    try:
        response = requests.get(endpoint, headers=headers)
        response.raise_for_status()
        data, latest_activity_info = parse_json_trivia(response)
        return data, latest_activity_info
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching trivia data for player {player_id}: {e}")
        return None, None

def fetch_sugarvita_data(player_id, start_date=None, end_date=None, auth_bearer=None):
    """
    Fetches sugarvita data for a player based on date range with proper authorization.
    """
    logger.info(f"Fetching sugarvita data for player {player_id}")

    # Convert dates to DD-MM-YYYY format that the GameBus API expects
    start_date = format_date_to_dd_mm_yyyy(start_date) if start_date else None
    end_date = format_date_to_dd_mm_yyyy(end_date) if end_date else None

    endpoint_pt = f"https://api3-new.gamebus.eu/v2/players/{player_id}/activities?gds=SUGARVITA_PLAYTHROUGH"
    endpoint_hl = f"https://api3-new.gamebus.eu/v2/players/{player_id}/activities?gds=SUGARVITA_ENGAGEMENT_LOG_1"

    if start_date:
        endpoint_pt += f"&start={start_date}"
        endpoint_hl += f"&start={start_date}"
    if end_date:
        endpoint_pt += f"&end={end_date}"
        endpoint_hl += f"&end={end_date}"

    headers = {"Authorization": f"Bearer {auth_bearer}"}

    try:
        response_pt = requests.get(endpoint_pt, headers=headers)
        response_hl = requests.get(endpoint_hl, headers=headers)
        response_pt.raise_for_status()
        response_hl.raise_for_status()

        data, latest_activity_info = parse_json_sugarvita(response_pt, response_hl)
        return data, latest_activity_info
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching sugarvita data for player {player_id}: {e}")
        return None, None

