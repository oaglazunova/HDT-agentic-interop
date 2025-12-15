from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

DEFAULT_USERS_PUBLIC = "users.json"
DEFAULT_USERS_SECRETS = "users.secrets.json"

IDENTITY_KEYS_DEFAULT = ("connected_application", "player_id")


def _load_users_file(path: Path) -> List[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or "users" not in data or not isinstance(data["users"], list):
        raise ValueError(f"Invalid users file format: {path}")
    return data["users"]


def _merge_lists_by_identity(
    pub_list: List[Dict[str, Any]],
    sec_list: List[Dict[str, Any]],
    identity_keys: Tuple[str, ...] = IDENTITY_KEYS_DEFAULT,
) -> List[Dict[str, Any]]:
    """
    Merge two lists of connector entries:
    - Match items by identity_keys (connected_application + player_id by default).
    - Overlay secret fields (e.g., auth_bearer) onto the public item.
    - Secrets cannot change identity fields.
    """
    merged: List[Dict[str, Any]] = []

    sec_index: Dict[Tuple[str, ...], List[Dict[str, Any]]] = {}
    for s in sec_list or []:
        key = tuple((s.get(k) or "") for k in identity_keys)
        sec_index.setdefault(key, []).append(s)

    for p in pub_list or []:
        key = tuple((p.get(k) or "") for k in identity_keys)
        s = (sec_index.get(key) or [None])[0]
        if s:
            over = {
                **p,
                **{k: v for k, v in s.items() if k not in set(identity_keys)},
            }
            merged.append(over)
        else:
            merged.append(p)

    return merged


def _merge_users(
    public_users: List[Dict[str, Any]],
    secret_users: List[Dict[str, Any]],
) -> Dict[int, Dict[str, Any]]:
    # Build secret lookup by user_id
    sec_by_uid = {int(u.get("user_id")): u for u in (secret_users or []) if "user_id" in u}

    merged_by_uid: Dict[int, Dict[str, Any]] = {}
    for pu in public_users or []:
        uid = int(pu["user_id"])
        su = sec_by_uid.get(uid, {})
        merged_entry = dict(pu)

        for key in ("connected_apps_diabetes_data", "connected_apps_walk_data", "connected_apps_nutrition_data"):
            merged_entry[key] = _merge_lists_by_identity(
                pu.get(key, []),
                (su or {}).get(key, []),
            )

        merged_by_uid[uid] = merged_entry

    return merged_by_uid


def load_users_merged(
    config_dir: Path,
    public_filename: str = DEFAULT_USERS_PUBLIC,
    secrets_filename: str = DEFAULT_USERS_SECRETS,
) -> Dict[int, Dict[str, Any]]:
    pub_path = config_dir / public_filename
    sec_path = config_dir / secrets_filename

    try:
        public = _load_users_file(pub_path)
    except FileNotFoundError:
        log.error("Users public file not found: %s", pub_path)
        public = []
    except Exception as e:
        log.error("Error loading %s: %s", pub_path, e)
        public = []

    try:
        secrets = _load_users_file(sec_path)
        log.info("Loaded users.secrets.json (overlay): %s", sec_path)
    except FileNotFoundError:
        secrets = []
        log.warning("users.secrets.json not found; proceeding without secrets overlay")
    except Exception as e:
        secrets = []
        log.error("Error loading %s: %s", sec_path, e)

    merged = _merge_users(public, secrets)
    log.info("Loaded %d users (merged)", len(merged))
    return merged


def get_connected_app_info(
    users_merged: Dict[int, Dict[str, Any]],
    user_id: int,
    app_type: str,
) -> Tuple[str, Optional[str], Optional[str]]:
    """
    Return (connected_application, player_id, auth_bearer) or ("Unknown", None, None).
    app_type should be one of: "walk_data", "diabetes_data", "nutrition_data".
    """
    user = users_merged.get(int(user_id))
    if not user:
        return "Unknown", None, None

    connected_apps_key = f"connected_apps_{app_type}"
    entries = user.get(connected_apps_key) or []
    if not entries:
        return "Unknown", None, None

    app_data = entries[0]  # first connector is primary
    return (
        app_data.get("connected_application", "Unknown"),
        app_data.get("player_id"),
        app_data.get("auth_bearer"),
    )


@dataclass(frozen=True)
class UsersStore:
    config_dir: Path

    def load(self) -> Dict[int, Dict[str, Any]]:
        return load_users_merged(self.config_dir)


__all__ = ["UsersStore", "load_users_merged", "get_connected_app_info"]
