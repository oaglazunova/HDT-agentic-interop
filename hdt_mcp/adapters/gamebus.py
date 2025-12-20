from typing import List, Optional
from hdt_mcp.domain.ports import WalkRecord
from hdt_sources_mcp.core_infrastructure.GAMEBUS_WALK_fetch import fetch_walk_data

def fetch_walk(player_id: str, auth_bearer: Optional[str]) -> List[WalkRecord]:
    # Thin wrapper around your GAMEBUS_WALK_fetch.fetch_walk_data
    data = fetch_walk_data(player_id, auth_bearer=auth_bearer) or []
    # here you can normalize shape if needed
    return data
