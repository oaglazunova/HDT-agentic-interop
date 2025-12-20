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

