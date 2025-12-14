"""
GameBus walk provider (fetch + parse).

Consolidates the legacy GAMEBUS_WALK_* modules.
"""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

# Convert Unix timestamp to local Dutch time (handling DST).
def convert_to_local_dutch_time(timestamp):
    """
    Convert a Unix timestamp to local Dutch time (Europe/Amsterdam).
    """
    timestamp_seconds = timestamp / 1000  # Convert milliseconds to seconds
    utc_time = datetime.fromtimestamp(timestamp_seconds, tz=timezone.utc)
    dutch_timezone = ZoneInfo('Europe/Amsterdam')
    local_time = utc_time.astimezone(dutch_timezone)
    return local_time.strftime('%Y-%m-%d %H:%M:%S')

# Convert seconds to HH:MM:SS format
def convert_seconds_to_hms(seconds):
    """
    Convert seconds to HH:MM:SS format.
    """
    return str(timedelta(seconds=int(seconds)))

# Parse walk activities data from the GameBus API
def parse_walk_activities(activities_json):
    """
    Parse walk activity data from the GameBus API response.
    """
    parsed_activities = []

    for activity in activities_json:
        activity_data = {}

        # Convert and store the activity date
        activity_data['date'] = convert_to_local_dutch_time(activity['date'])

        # Initialize activity metrics
        steps = None
        distance = None
        duration = None
        kcalories = None

        # Extract property instances
        for property_instance in activity.get('propertyInstances', []):
            prop_key = property_instance['property']['translationKey']
            value = property_instance['value']
            base_unit = property_instance['property']['baseUnit']

            if prop_key == 'STEPS':
                steps = float(value)
            elif prop_key == 'DISTANCE':
                if base_unit == 'meters':
                    distance = float(value)
                elif base_unit == 'centimeters':
                    distance = float(value) / 100
                elif base_unit == 'kilometers':
                    distance = float(value) * 1000
            elif prop_key == 'DURATION':
                if base_unit == 'seconds':
                    duration = convert_seconds_to_hms(value)
                elif base_unit == 'minutes':
                    duration = convert_seconds_to_hms(float(value) * 60)
                elif base_unit == 'hours':
                    duration = convert_seconds_to_hms(float(value) * 3600)
            elif prop_key == 'KCALORIES':
                kcalories = float(value)

        # Store the parsed metrics
        activity_data['steps'] = steps
        activity_data['distance_meters'] = distance
        activity_data['duration'] = duration
        activity_data['kcalories'] = kcalories

        parsed_activities.append(activity_data)

    return parsed_activities

import requests

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
