from typing import List, Optional
from hdt_mcp.domain.ports import WalkRecord

def fetch_walk(player_id: str, auth_bearer: Optional[str]) -> List[WalkRecord]:
    # Thin wrapper around your GOOGLE_FIT_WALK_fetch.fetch_google_fit_walk_data
    from hdt_core_infrastructure.GOOGLE_FIT_WALK_fetch import fetch_google_fit_walk_data
    data = fetch_google_fit_walk_data(player_id, auth_bearer=auth_bearer) or []
    # here you can normalize shape if needed
    return data
