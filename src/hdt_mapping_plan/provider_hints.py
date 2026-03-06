from __future__ import annotations


_PROVIDER_SEED_POINTER_CANDIDATES: dict[str, dict[str, list[str]]] = {
    "provider.obesityCoach": {
        "/recordId": ["txn_id"],
        "/person/birthDate": ["dob"],
        "/day/date": ["date"],
        "/activity/steps": ["steps"],
        "/nutrition/caloriesIn": ["calories_in"],
        "/hydration/waterMl": ["water_ml"],
        "/sleep/minutes": ["sleep_minutes"],
    }
}


def provider_seed_pointer_candidates(algo_id: str) -> dict[str, list[str]]:
    base = _PROVIDER_SEED_POINTER_CANDIDATES.get(algo_id, {})
    return {ptr: list(cols) for ptr, cols in base.items()}
