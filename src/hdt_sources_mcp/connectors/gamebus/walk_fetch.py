import logging
import os

from hdt_sources_mcp.connectors.gamebus.walk_parse import parse_walk_activities
from hdt_sources_mcp.connectors.gamebus.diabetes_fetch import format_date_to_dd_mm_yyyy
from hdt_sources_mcp.core_infrastructure.http_client import DEFAULT_HTTP_CLIENT


logger = logging.getLogger(__name__)

GAMEBUS_BASE_URL = os.getenv("HDT_GAMEBUS_BASE_URL", "https://api3-new.gamebus.eu/v2").rstrip("/")


def _auth_headers(auth_bearer: str | None) -> dict[str, str]:
    if not auth_bearer:
        return {}
    t = str(auth_bearer).strip()
    if not t.lower().startswith("bearer "):
        t = f"Bearer {t}"
    return {"Authorization": t}


def fetch_walk_data(player_id, auth_bearer, start_date: str | None = None, end_date: str | None = None):
    """Fetch WALK activities for a GameBus player.

    Args:
        player_id: GameBus player.id
        auth_bearer: access token (with or without 'Bearer ' prefix)
        start_date/end_date: optional date window. Accepts YYYY-MM-DD, ISO timestamps, or DD-MM-YYYY.
            If provided, converted to DD-MM-YYYY which GameBus expects for these parameters.
    """
    endpoint = f"{GAMEBUS_BASE_URL}/players/{player_id}/activities"
    params: dict[str, str] = {"gds": "WALK"}

    sd = format_date_to_dd_mm_yyyy(start_date) if start_date else None
    ed = format_date_to_dd_mm_yyyy(end_date) if end_date else None
    if sd:
        params["start"] = sd
    if ed:
        params["end"] = ed

    headers = _auth_headers(auth_bearer)

    try:
        activities_json = DEFAULT_HTTP_CLIENT.get_json(endpoint, headers=headers, params=params)
        return parse_walk_activities(activities_json)
    except Exception as e:
        logger.error("Error fetching/parsing walk data for player %s: %s", player_id, e)
        return None
