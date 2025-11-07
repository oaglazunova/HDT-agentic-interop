import json
import logging

logger = logging.getLogger(__name__)

from datetime import datetime

def parse_json_trivia(response_trivia):
    """
    Parse trivia data dynamically from the GameBus API response.

    Args:
        response_trivia: The HTTP response from the GameBus API containing trivia data

    Returns:
        tuple: (metrics, latest_activity_info)
            - metrics: Dictionary containing counts of questions answered with/without hints
              and correct/incorrect answers
            - latest_activity_info: Dictionary containing the ID and timestamp of the latest activity

    Raises:
        No exceptions are raised as they are caught and logged internally
    """
    metrics = {
        "WITH_HINT": {
            "TRUE": 0,  # Counts questions answered with a hint
            "FALSE": 0,  # Counts questions answered without a hint
        },
        "NO_HINT_TYPE_OF_ANSWER": {
            "CORRECT": 0,  # Questions answered correctly without a hint
            "INCORRECT": 0,  # Questions answered incorrectly without a hint
        }
    }
    latest_activity_info = {"id": None, "timestamp": None}

    try:
        # Check if response is valid
        if not response_trivia or not hasattr(response_trivia, 'text') or not response_trivia.text:
            logger.warning("Empty or invalid response received from GameBus API")
            return metrics, latest_activity_info

        parsed_response_trivia = json.loads(response_trivia.text)

        # Check if we have any activities
        if not parsed_response_trivia:
            logger.info("No trivia activities found in the response")
            return metrics, latest_activity_info

        # Sort by date in descending order to get the most recent activity
        try:
            sorted_activities = sorted(parsed_response_trivia, key=lambda x: x["date"], reverse=True)
            latest_activity = sorted_activities[0]
            latest_activity_info["id"] = latest_activity["id"]
            # Convert UNIX timestamp to human-readable format
            latest_activity_info["timestamp"] = datetime.utcfromtimestamp(latest_activity["date"] / 1000).strftime('%Y-%m-%d %H:%M:%S')
            logger.info(f"Latest trivia activity found: ID {latest_activity_info['id']} at {latest_activity_info['timestamp']}")
        except (KeyError, IndexError) as e:
            logger.error(f"Error extracting latest activity info: {str(e)}")

        # Process each record
        for record_index, record in enumerate(parsed_response_trivia):
            through_hint = None

            if "propertyInstances" not in record:
                logger.warning(f"Record {record_index} missing propertyInstances")
                continue

            for element in record["propertyInstances"]:
                try:
                    if "property" not in element or "translationKey" not in element["property"]:
                        continue

                    if element["property"]["translationKey"] == "THROUGH_HINT":
                        if element["value"] == "true":
                            metrics["WITH_HINT"]["TRUE"] += 1
                            through_hint = True
                        elif element["value"] == "false":
                            metrics["WITH_HINT"]["FALSE"] += 1
                            through_hint = False
                except Exception as e:
                    logger.error(f"Error parsing THROUGH_HINT in record {record_index}: {str(e)}")

                try:
                    if (
                        element["property"]["translationKey"] == "QUESTION_CORRECT"
                        and through_hint is False
                    ):
                        if element["value"] == "true":
                            metrics["NO_HINT_TYPE_OF_ANSWER"]["CORRECT"] += 1
                        elif element["value"] == "false":
                            metrics["NO_HINT_TYPE_OF_ANSWER"]["INCORRECT"] += 1
                except Exception as e:
                    logger.error(f"Error parsing QUESTION_CORRECT in record {record_index}: {str(e)}")
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error parsing trivia response: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error parsing trivia response: {str(e)}")

    logger.info(f"Parsed trivia metrics: {metrics}")
    return metrics, latest_activity_info



def parse_json_sugarvita(response_pt, response_hl):
    """
    Parse sugarvita data dynamically from the GameBus API responses for playthrough and engagement logs.
    """
    metrics_per_session = {
        "SCORES": [],
        "PLAYTIMES": [],
        "DAYS_PLAYED": [],
        "HOME_PATH": [],
        "WORK_PATH": [],
        "OUTDOORS_PATH": [],
        "GLUCOSE_ACCURACY": [],
        "GLUCOSE_LEVELS": [],
        "SCORE_VARIATION": [],
        "TOTAL_TRIPS_HOSPITAL": [],
        "GLUCOSE_CRITICAL_VALUE_RESPONSE": [],
        "TURN_TIME": [],
    }
    latest_activity_info = {"playthrough": {"id": None, "timestamp": None}, "engagement": {"id": None, "timestamp": None}}

    try:
        parsed_response_pt = json.loads(response_pt.text)
        parsed_response_hl = json.loads(response_hl.text)

        # Sort playthrough data by date in descending order
        if parsed_response_pt:
            sorted_playthrough = sorted(parsed_response_pt, key=lambda x: x["date"], reverse=True)
            latest_playthrough = sorted_playthrough[0]
            latest_activity_info["playthrough"]["id"] = latest_playthrough["id"]
            # Convert UNIX timestamp to human-readable format
            latest_activity_info["playthrough"]["timestamp"] = datetime.utcfromtimestamp(latest_playthrough["date"] / 1000).strftime('%Y-%m-%d %H:%M:%S')

        # Sort engagement data by date in descending order
        if parsed_response_hl:
            sorted_engagement = sorted(parsed_response_hl, key=lambda x: x["date"], reverse=True)
            latest_engagement = sorted_engagement[0]
            latest_activity_info["engagement"]["id"] = latest_engagement["id"]
            # Convert UNIX timestamp to human-readable format
            latest_activity_info["engagement"]["timestamp"] = datetime.utcfromtimestamp(latest_engagement["date"] / 1000).strftime('%Y-%m-%d %H:%M:%S')

        # Parse playthrough data
        for record in parsed_response_pt:
            for element in record["propertyInstances"]:
                try:
                    if element["property"]["translationKey"] == "SCORE":
                        metrics_per_session["SCORES"].append(int(element["value"]))
                except:
                    metrics_per_session["SCORES"].append("NaN")

                try:
                    if element["property"]["translationKey"] == "PLAYTIME":
                        metrics_per_session["PLAYTIMES"].append(int(element["value"]))
                except:
                    metrics_per_session["PLAYTIMES"].append("NaN")

                try:
                    if element["property"]["translationKey"] == "GLUCOSE_RANGE_PERCENTAGE":
                        metrics_per_session["GLUCOSE_ACCURACY"].append(
                            int(element["value"])
                        )
                except Exception as e:
                    logger.error(f"Error parsing GLUCOSE_RANGE_PERCENTAGE: {str(e)}")

                try:
                    if element["property"]["translationKey"] == "PLAYTHROUGH_DATA":
                        playthrough_data = json.loads(element["value"])
                        metrics_per_session["DAYS_PLAYED"].append(playthrough_data["daysPlayed"])
                        home_path, outdoors_path, work_path = 0, 0, 0

                        for turn in playthrough_data["turns"]:
                            if turn["DestinationPathType"] == 1:
                                home_path += 1
                            elif turn["DestinationPathType"] == 2:
                                outdoors_path += 1
                            elif turn["DestinationPathType"] == 3:
                                work_path += 1

                        metrics_per_session["HOME_PATH"].append(home_path)
                        metrics_per_session["WORK_PATH"].append(work_path)
                        metrics_per_session["OUTDOORS_PATH"].append(outdoors_path)
                except Exception as e:
                    logger.error(f"Error parsing PLAYTHROUGH_DATA: {str(e)}")

        # Parse engagement logs
        for record in parsed_response_hl:
            current_score = []
            glucose_values_each_turn = []
            turn_time = []
            is_hospitalised = 0

            for element in record["propertyInstances"]:
                try:
                    if element["property"]["translationKey"] == "ENGAGEMENT_DATA":
                        engagement_data = json.loads(element["value"])
                        for gameplaydata in engagement_data["GameplayData"]:
                            gameplaydata_values = json.loads(gameplaydata["Values"][0])
                            if gameplaydata_values["aborted"] is False:
                                for turn in gameplaydata_values["turns"]:
                                    if turn["CurrentScore"] != 0:
                                        current_score.append(turn["CurrentScore"])
                                    if turn["IsHospitalised"]:
                                        is_hospitalised += 1
                                    if glucose_values_each_turn == [] and turn_time == []:
                                        glucose_values_each_turn.append(turn["GlucoseValueStart"])
                                        if turn["GlucoseValueEnd"] != 0.0:
                                            glucose_values_each_turn.append(turn["GlucoseValueEnd"])
                                        turn_time.append(turn["MinutesStart"])
                                        if turn["MinutesEnd"] != 0:
                                            turn_time.append(turn["MinutesEnd"])
                                    else:
                                        glucose_values_each_turn.append(turn["GlucoseValueEnd"])
                                        turn_time.append(turn["MinutesEnd"])

                                if current_score and turn_time and glucose_values_each_turn:
                                    metrics_per_session["SCORE_VARIATION"].append(current_score[:-1] if current_score[-1] == 0 else current_score)
                                    metrics_per_session["TURN_TIME"].append(turn_time[:-1] if turn_time[-1] == 0 else turn_time)
                                    metrics_per_session["GLUCOSE_LEVELS"].append(glucose_values_each_turn[:-1] if glucose_values_each_turn[-1] == 0 else glucose_values_each_turn)
                                    metrics_per_session["TOTAL_TRIPS_HOSPITAL"].append(is_hospitalised)
                except Exception as e:
                    logger.error(f"Error parsing ENGAGEMENT_DATA: {str(e)}")

        # Calculate critical glucose values
        metrics_per_session["GLUCOSE_CRITICAL_VALUE_RESPONSE"] = get_glucose_critical_value_response(
            metrics_per_session["GLUCOSE_LEVELS"], metrics_per_session["TURN_TIME"]
        )
    except Exception as e:
        logger.error(f"Error parsing sugarvita response: {str(e)}")

    return metrics_per_session, latest_activity_info


def get_glucose_critical_value_response(glucose_levels, times):
    """
    Calculate critical glucose values dynamically.

    This function analyzes glucose level readings and their timestamps to determine
    how quickly a user responds to critical (red) glucose values by bringing them
    back to normal (green) range.

    Args:
        glucose_levels (list): List of lists containing glucose readings for each playthrough
        times (list): List of lists containing timestamps for each glucose reading

    Returns:
        list: List of response times (in minutes) between red and green glucose values
    """
    glucose_critical_value_response = []

    values_to_calculate_critical_value_response = {
        "red_glucose_value": -1,
        "closest_green_glucose_value": -1,
        "time_red": -1,
        "time_closest_green": -1,
    }

    blood_glucose_colored_regions = {
        "red": [(0, 2.6), (15, 20)],
        "green": [(4.5, 8)],
        # Other ranges omitted for brevity
    }

    for glucose_playthrough, times_playthrough in zip(glucose_levels, times):
        # Skip if either list is empty
        if not glucose_playthrough or not times_playthrough:
            continue

        # Reset values for this playthrough
        values = reset_dictionary_values(values_to_calculate_critical_value_response.copy())

        # Iterate through glucose values to find red values
        for i, glucose in enumerate(glucose_playthrough):
            # Check if glucose is in red region
            is_red = False
            for red_range in blood_glucose_colored_regions["red"]:
                if red_range[0] <= glucose <= red_range[1]:
                    is_red = True
                    break

            if is_red and values["red_glucose_value"] == -1:
                # Found first red value
                values["red_glucose_value"] = glucose
                values["time_red"] = times_playthrough[i]

                # Look for closest green value after this red value
                for j in range(i+1, len(glucose_playthrough)):
                    next_glucose = glucose_playthrough[j]

                    # Check if next glucose is in green region
                    is_green = False
                    for green_range in blood_glucose_colored_regions["green"]:
                        if green_range[0] <= next_glucose <= green_range[1]:
                            is_green = True
                            break

                    if is_green:
                        # Found green value after red
                        values["closest_green_glucose_value"] = next_glucose
                        values["time_closest_green"] = times_playthrough[j]
                        break

                # If we found both red and green values, calculate response time
                if values["red_glucose_value"] != -1 and values["closest_green_glucose_value"] != -1:
                    response_time = values["time_closest_green"] - values["time_red"]
                    if response_time > 0:  # Ensure positive response time
                        glucose_critical_value_response.append(response_time)
                    break

    return glucose_critical_value_response


def reset_dictionary_values(some_dict) -> dict:
    """
    Reset dictionary values to their default state.
    """
    for key in some_dict:
        some_dict[key] = -1
    return some_dict
