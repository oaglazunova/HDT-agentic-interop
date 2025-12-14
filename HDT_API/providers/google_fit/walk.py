"""
Google Fit walk provider (fetch + parse).

Consolidates the legacy GOOGLE_FIT_WALK_* modules.
"""

from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo


def parse_google_fit_walk_data(google_fit_data):
    """
    Parse Google Fit step count data into a format similar to GameBus walk data.

    Args:
        google_fit_data (dict): Raw response from the Google Fit API.

    Returns:
        list: Parsed walk activity data.
    """
    parsed_activities = []
    amsterdam_tz = ZoneInfo("Europe/Amsterdam")

    for point in google_fit_data.get("point", []):
        start_time_ns = int(point["startTimeNanos"])
        end_time_ns = int(point["endTimeNanos"])
        steps = next(
            (value["intVal"] for value in point["value"] if "intVal" in value),
            None,
        )

        # Convert nanoseconds to datetime
        start_time = datetime.fromtimestamp(start_time_ns / 1e9, tz=timezone.utc).astimezone(amsterdam_tz)
        end_time = datetime.fromtimestamp(end_time_ns / 1e9, tz=timezone.utc).astimezone(amsterdam_tz)

        # Calculate duration in HH:MM:SS format
        duration_seconds = (end_time - start_time).total_seconds()
        duration = str(timedelta(seconds=int(duration_seconds)))

        parsed_activities.append({
            "date": start_time.strftime("%Y-%m-%d %H:%M:%S"),
            "steps": steps,
            "distance_meters": None,  # Google Fit step count doesn't include distance
            "duration": duration if duration_seconds > 0 else None,
            "kcalories": None,  # This data is not available in step count API
        })

    return parsed_activities

import requests
import logging

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
