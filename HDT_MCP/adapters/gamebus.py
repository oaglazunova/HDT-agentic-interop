from typing import List, Optional
from HDT_MCP.domain.ports import WalkRecord

def fetch_walk(player_id: str, auth_bearer: Optional[str]) -> List[WalkRecord]:
    # Thin wrapper around your GAMEBUS_WALK_fetch.fetch_walk_data
    from HDT_CORE_INFRASTRUCTURE.GAMEBUS_WALK_fetch import fetch_walk_data
    data = fetch_walk_data(player_id, auth_bearer=auth_bearer) or []
    # here you can normalize shape if needed
    return data
