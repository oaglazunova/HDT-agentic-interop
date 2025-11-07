from statistics import mean, pstdev
from sklearn.preprocessing import MinMaxScaler

# Manipulate initial metrics for trivia
def manipulate_initial_metrics_trivia(metrics_cleaned):
    metrics_overview_hl_trivia = {
        "avg_hint": 0,
        "avg_correct": 0,
        "avg_incorrect": 0,
    }

    total_trivia_answers = metrics_cleaned["WITH_HINT"]["TRUE"] + metrics_cleaned["WITH_HINT"]["FALSE"]

    # Avoid division by zero for avg_hint
    if total_trivia_answers > 0:
        metrics_overview_hl_trivia["avg_hint"] = metrics_cleaned["WITH_HINT"]["TRUE"] / total_trivia_answers

    # Avoid division by zero for avg_correct and avg_incorrect
    if metrics_cleaned["WITH_HINT"]["FALSE"] > 0:
        metrics_overview_hl_trivia["avg_correct"] = metrics_cleaned["NO_HINT_TYPE_OF_ANSWER"]["CORRECT"] / metrics_cleaned["WITH_HINT"]["FALSE"]
        metrics_overview_hl_trivia["avg_incorrect"] = metrics_cleaned["NO_HINT_TYPE_OF_ANSWER"]["INCORRECT"] / metrics_cleaned["WITH_HINT"]["FALSE"]

    return metrics_overview_hl_trivia

# Manipulate initial metrics for SugarVita
def manipulate_initial_metrics_sugarvita(metrics_cleaned):
    metrics_overview_pt_sugarvita = {
        "avg_score": 0,
        "sd_score": 0,
        "avg_playtimes": 0,
        "sd_playtimes": 0,
        "avg_days_session": 0,
        "sd_days_session": 0,
        "total_home_path": 0,
        "total_outdoors_path": 0,
        "total_work_path": 0,
    }

    metrics_overview_hl_sugarvita = {
        "avg_glucose_accuracy": 0,
        "trips_to_hospital_per_game": 0,
        "avg_glucose_critical_value_response": 0,
    }

    if metrics_cleaned["SCORES"]:
        metrics_overview_pt_sugarvita["avg_score"] = mean(metrics_cleaned["SCORES"])
        if len(metrics_cleaned["SCORES"]) > 1:
            metrics_overview_pt_sugarvita["sd_score"] = pstdev(metrics_cleaned["SCORES"])

    if metrics_cleaned["PLAYTIMES"]:
        metrics_overview_pt_sugarvita["avg_playtimes"] = mean(metrics_cleaned["PLAYTIMES"])
        if len(metrics_cleaned["PLAYTIMES"]) > 1:
            metrics_overview_pt_sugarvita["sd_playtimes"] = pstdev(metrics_cleaned["PLAYTIMES"])

    if metrics_cleaned["DAYS_PLAYED"]:
        metrics_overview_pt_sugarvita["avg_days_session"] = mean(metrics_cleaned["DAYS_PLAYED"])
        if len(metrics_cleaned["DAYS_PLAYED"]) > 1:
            metrics_overview_pt_sugarvita["sd_days_session"] = pstdev(metrics_cleaned["DAYS_PLAYED"])

    metrics_overview_pt_sugarvita["total_home_path"] = sum(metrics_cleaned["HOME_PATH"])
    metrics_overview_pt_sugarvita["total_outdoors_path"] = sum(metrics_cleaned["OUTDOORS_PATH"])
    metrics_overview_pt_sugarvita["total_work_path"] = sum(metrics_cleaned["WORK_PATH"])

    if metrics_cleaned["GLUCOSE_ACCURACY"]:
        metrics_overview_hl_sugarvita["avg_glucose_accuracy"] = mean(metrics_cleaned["GLUCOSE_ACCURACY"])

    if metrics_cleaned["TOTAL_TRIPS_HOSPITAL"]:
        trips = len(metrics_cleaned["TOTAL_TRIPS_HOSPITAL"])
        if trips > 0:
            metrics_overview_hl_sugarvita["trips_to_hospital_per_game"] = sum(metrics_cleaned["TOTAL_TRIPS_HOSPITAL"]) / trips

    if metrics_cleaned["GLUCOSE_CRITICAL_VALUE_RESPONSE"]:
        metrics_overview_hl_sugarvita["avg_glucose_critical_value_response"] = mean(metrics_cleaned["GLUCOSE_CRITICAL_VALUE_RESPONSE"])

    return metrics_overview_pt_sugarvita, metrics_overview_hl_sugarvita

# Normalize metrics
def normalize_metrics(metrics_overview):
    values = [[value] for value in metrics_overview.values()]
    scaler = MinMaxScaler()
    normalized_values = scaler.fit_transform(values)
    return {key: normalized_value[0] for key, normalized_value in zip(metrics_overview.keys(), normalized_values)}

# Calculate the final scores
def calculate_score(weights, metrics_normalized):
    positive, negative = 0, 0
    for key, value in weights.items():
        if value > 0:
            positive += value * metrics_normalized[key]
        else:
            negative += value * metrics_normalized[key]
    return positive + negative

def get_health_literacy_score_trivia(metrics_normalized):
    weights = {"avg_hint": -0.15, "avg_correct": 1, "avg_incorrect": -0.85}
    return calculate_score(weights, metrics_normalized)

def get_health_literacy_score_sugarvita(metrics_normalized):
    weights = {"avg_glucose_critical_value_response": 0.15, "trips_to_hospital_per_game": -1, "avg_glucose_accuracy": 0.85}
    return calculate_score(weights, metrics_normalized)

def get_final_health_literacy_score(trivia_score, sugarvita_score):
    weights = {"trivia": 0.6, "sugarvita": 0.4}
    return (weights["trivia"] * trivia_score) + (weights["sugarvita"] * sugarvita_score)

def get_player_types(metrics_normalized):
    types = {
        "Socializer": {"total_home_path": 0.5, "total_outdoors_path": 0.5},
        "Competitive": {"avg_score": 0.3, "sd_score": 0.05},
        "Explorer": {"avg_playtimes": 0.3, "avg_days_session": 0.15},
    }
    return {ptype: calculate_score(weights, metrics_normalized) for ptype, weights in types.items()}
