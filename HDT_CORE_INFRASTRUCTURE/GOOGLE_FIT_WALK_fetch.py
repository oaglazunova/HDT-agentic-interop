import requests
import logging
from HDT_CORE_INFRASTRUCTURE.GOOGLE_FIT_WALK_parse import parse_google_fit_walk_data

logger = logging.getLogger(__name__)

GOOGLE_FIT_ENDPOINT_TEMPLATE = "https://www.googleapis.com/fitness/v1/users/{player_id}/dataSources/derived:com.google.step_count.delta:com.google.android.gms:merge_step_deltas/datasets/{start_time}-{end_time}"


def fetch_google_fit_walk_data(player_id, auth_bearer, start_time=0, end_time=4102444800000000000):
    """
    Fetch step count data from Google Fit and parse it.

    Args:
        player_id (str): Google Fit player ID (usually "me").
        auth_bearer (str): Authorization token for Google Fit API.
        start_time (str): Start time in nanoseconds (default is '0' for all data).
        end_time (str): End time in nanoseconds (default is maximum for all data).

    Returns:
        list: Parsed walk activity data or None if an error occurs.
    """
    headers = {"Authorization": f"Bearer {auth_bearer}"}
    url = GOOGLE_FIT_ENDPOINT_TEMPLATE.format(player_id=player_id, start_time=start_time, end_time=end_time)

    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        raw_data = response.json()

        return parse_google_fit_walk_data(raw_data)
    except requests.RequestException as e:
        logger.error(f"Error fetching Google Fit walk data for player {player_id}: {e}")
        return None



