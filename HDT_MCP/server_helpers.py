import json, os
from typing import Tuple, Optional

def resolve_connected_app(user_id: int, app_type: str) -> Tuple[str, Optional[str], Optional[str]]:
    # exactly mirroring your Flask get_connected_app_info
    with open("config/users.json","r",encoding="utf-8") as f:
        root = json.load(f)
    users = {int(u["user_id"]): u for u in root.get("users", [])}
    u = users.get(user_id, {})
    key = f"connected_apps_{app_type}"
    arr = u.get(key) or []
    if not arr:
        return "Unknown", None, None
    app = arr[0]
    return app.get("connected_application","Unknown"), app.get("player_id"), app.get("auth_bearer")
