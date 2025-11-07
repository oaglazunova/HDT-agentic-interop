from __future__ import annotations
import json
from functools import wraps
from typing import Callable

with open("config/user_permissions.json","r",encoding="utf-8") as f:
    PERM = json.load(f)

def enforce(user_param: str="user_id", action: str="read"):
    def deco(fn: Callable):
        @wraps(fn)
        def _wrap(*args, **kwargs):
            user_id = kwargs.get(user_param) or (args[0] if args else None)
            if not user_id:  # fail-closed
                raise PermissionError("Missing user_id")
            allowed = PERM.get(user_id, {}).get("allowed_actions", [])
            if action not in allowed:
                raise PermissionError(f"Action '{action}' not permitted for {user_id}")
            return fn(*args, **kwargs)
        return _wrap
    return deco
