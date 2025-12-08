from typing import List, Optional
from HDT_MCP.domain.ports import WalkRecord, DateRange
from HDT_MCP.adapters import gamebus, google_fit

def sync_user_walk(app_name: str, player_id: str, auth_bearer: Optional[str]) -> List[WalkRecord]:
    name = (app_name or "").strip().lower()
    if name == "gamebus":
        return gamebus.fetch_walk(player_id, auth_bearer)
    if name in ("google fit", "googlefit", "google_fit"):
        return google_fit.fetch_walk(player_id, auth_bearer)
    # placeholder demo path – keep parity with your Flask side
    if name.startswith("placeholder"):
        from datetime import date, timedelta
        today = date.today()
        return [
            {"date": (today - timedelta(days=2)).isoformat(), "steps": 4231,
             "distance_meters": None, "duration": None, "kcalories": None},
            {"date": (today - timedelta(days=1)).isoformat(), "steps": 6120,
             "distance_meters": None, "duration": None, "kcalories": None},
            {"date": today.isoformat(), "steps": 3580,
             "distance_meters": None, "duration": None, "kcalories": None},
        ]
    return []
