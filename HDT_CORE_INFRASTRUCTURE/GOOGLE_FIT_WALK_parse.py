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

