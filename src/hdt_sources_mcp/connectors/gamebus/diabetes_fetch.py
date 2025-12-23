import logging
import os
import re
from datetime import datetime, timezone

from .diabetes_parse import parse_json_trivia, parse_json_sugarvita
from ...core_infrastructure.http_client import DEFAULT_HTTP_CLIENT


logger = logging.getLogger(__name__)

GAMEBUS_BASE_URL = os.getenv("HDT_GAMEBUS_BASE_URL", "https://api3-new.gamebus.eu/v2").rstrip("/")


def _auth_headers(auth_bearer: str | None) -> dict[str, str]:
    if not auth_bearer:
        return {}
    t = str(auth_bearer).strip()
    if not t.lower().startswith("bearer "):
        t = f"Bearer {t}"
    return {"Authorization": t}


def format_date_to_dd_mm_yyyy(date_str: str | None) -> str | None:
    """Convert a loose date/time string to DD-MM-YYYY (GameBus API expectation).

    Accepts:
    - DD-MM-YYYY (returned as-is)
    - YYYY-MM-DD
    - ISO timestamps like YYYY-MM-DDTHH:MM:SSZ or with offsets
    - naive timestamps (treated as UTC)
    """
    if not date_str:
        return None

    s = str(date_str).strip()
    if not s:
        return None

    # Already in DD-MM-YYYY
    if re.match(r"^\d{2}-\d{2}-\d{4}$", s):
        return s

    # Date-only YYYY-MM-DD
    try:
        if len(s) == 10 and s[4] == "-" and s[7] == "-":
            dt = datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            return dt.strftime("%d-%m-%Y")
    except Exception:
        pass

    # ISO-ish timestamps
    try:
        iso = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).strftime("%d-%m-%Y")
    except Exception:
        pass

    # Legacy strict pattern (last resort)
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").strftime("%d-%m-%Y")
    except Exception:
        logger.warning("Invalid date format: %s. Skipping conversion.", s)
        return None


def fetch_trivia_data(player_id, start_date=None, end_date=None, auth_bearer=None):
    logger.info("Fetching trivia data for player %s", player_id)

    start_date = format_date_to_dd_mm_yyyy(start_date) if start_date else None
    end_date = format_date_to_dd_mm_yyyy(end_date) if end_date else None

    endpoint = f"{GAMEBUS_BASE_URL}/players/{player_id}/activities"
    params: dict[str, str] = {"gds": "ANSWER_TRIVIA_DIABETES"}
    if start_date:
        params["start"] = start_date
    if end_date:
        params["end"] = end_date

    headers = _auth_headers(auth_bearer)

    try:
        response = DEFAULT_HTTP_CLIENT.get(endpoint, headers=headers, params=params)
        data, latest_activity_info = parse_json_trivia(response)
        return data, latest_activity_info
    except Exception as e:
        logger.error("Error fetching trivia data for player %s: %s", player_id, e)
        return None, None


def fetch_sugarvita_data(player_id, start_date=None, end_date=None, auth_bearer=None):
    logger.info("Fetching sugarvita data for player %s", player_id)

    start_date = format_date_to_dd_mm_yyyy(start_date) if start_date else None
    end_date = format_date_to_dd_mm_yyyy(end_date) if end_date else None

    endpoint = f"{GAMEBUS_BASE_URL}/players/{player_id}/activities"
    params_pt: dict[str, str] = {"gds": "SUGARVITA_PLAYTHROUGH"}
    params_hl: dict[str, str] = {"gds": "SUGARVITA_ENGAGEMENT_LOG_1"}

    if start_date:
        params_pt["start"] = start_date
        params_hl["start"] = start_date
    if end_date:
        params_pt["end"] = end_date
        params_hl["end"] = end_date

    headers = _auth_headers(auth_bearer)

    try:
        response_pt = DEFAULT_HTTP_CLIENT.get(endpoint, headers=headers, params=params_pt)
        response_hl = DEFAULT_HTTP_CLIENT.get(endpoint, headers=headers, params=params_hl)

        data, latest_activity_info = parse_json_sugarvita(response_pt, response_hl)
        return data, latest_activity_info
    except Exception as e:
        logger.error("Error fetching sugarvita data for player %s: %s", player_id, e)
        return None, None
