from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Tuple


def _load_users_file(path: Path) -> List[Dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "users" not in data or not isinstance(data["users"], list):
        raise ValueError(f"Invalid users file format: {path}")
    return list(data["users"])


def _merge_lists_by_identity(
    pub_list: List[Dict[str, Any]],
    sec_list: List[Dict[str, Any]],
    *,
    identity_keys: Tuple[str, str] = ("connected_application", "player_id"),
) -> List[Dict[str, Any]]:
    """Merge two connector lists by identity; overlay secrets onto public items."""
    merged: List[Dict[str, Any]] = []

    sec_index: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for s in sec_list or []:
        key = tuple((s.get(k) or "") for k in identity_keys)  # type: ignore[misc]
        sec_index.setdefault(key, []).append(s)

    for p in pub_list or []:
        key = tuple((p.get(k) or "") for k in identity_keys)  # type: ignore[misc]
        s = (sec_index.get(key) or [None])[0]
        if s:
            over = {**p, **{k: v for k, v in s.items() if k not in set(identity_keys)}}
            merged.append(over)
        else:
            merged.append(p)

    return merged


def _merge_users(
    public_users: List[Dict[str, Any]],
    secret_users: List[Dict[str, Any]],
) -> Dict[int, Dict[str, Any]]:
    sec_by_uid = {int(u.get("user_id")): u for u in secret_users or [] if "user_id" in u}

    merged_by_uid: Dict[int, Dict[str, Any]] = {}
    for pu in public_users:
        uid = int(pu["user_id"])
        su = sec_by_uid.get(uid, {})
        merged_entry = dict(pu)

        for key in (
            "connected_apps_diabetes_data",
            "connected_apps_walk_data",
            "connected_apps_nutrition_data",
        ):
            merged_entry[key] = _merge_lists_by_identity(pu.get(key, []), (su or {}).get(key, []))

        merged_by_uid[uid] = merged_entry

    return merged_by_uid


@dataclass(frozen=True)
class UsersStore:
    """In-memory merged view of users.json + users.secrets.json."""

    users: Mapping[int, Mapping[str, Any]]

    @classmethod
    def from_repo_root(cls, repo_root: Path, *, logger: Optional[logging.Logger] = None) -> "UsersStore":
        log = logger or logging.getLogger(__name__)
        cfg_dir = repo_root / "config"
        public_path = cfg_dir / "users.json"
        secrets_path = cfg_dir / "users.secrets.json"

        try:
            public = _load_users_file(public_path)
        except FileNotFoundError:
            log.error("Users public file not found: %s", public_path)
            public = []
        except Exception as e:
            log.error("Error loading users.json: %s", e)
            public = []

        try:
            secrets = _load_users_file(secrets_path)
            log.info("Loaded users.secrets.json (overlay)")
        except FileNotFoundError:
            secrets = []
            log.warning("users.secrets.json not found; proceeding without secrets overlay")
        except Exception as e:
            secrets = []
            log.error("Error loading users.secrets.json: %s", e)

        merged = _merge_users(public, secrets)
        log.info("Loaded %d users (merged)", len(merged))
        return cls(users=merged)

    def get_connected_app_info(self, user_id: int, app_type: str) -> Tuple[str, Optional[str], Optional[str]]:
        """Return (connected_application, player_id, auth_bearer) or ("Unknown", None, None)."""
        user = self.users.get(int(user_id))
        if not user:
            return "Unknown", None, None

        entries = user.get(f"connected_apps_{app_type}") or []
        if not entries:
            return "Unknown", None, None

        app_data = entries[0]
        return (
            str(app_data.get("connected_application", "Unknown")),
            app_data.get("player_id"),
            app_data.get("auth_bearer"),
        )

    @classmethod
    def from_files(cls, public_path, secrets_path, logger):
        pass
