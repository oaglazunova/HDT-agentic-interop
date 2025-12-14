from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Union

RepoConfig = Union[List[Dict[str, Any]], Dict[str, Any]]


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_external_parties(repo_root: Path) -> RepoConfig:
    """
    Load external parties configuration.

    Preferred: config/config.py (repo-level package) if present.
    Fallback: repo_root/config/external_parties.json
    """
    try:
        from config.config import load_external_parties as _loader  # type: ignore
        return _loader()
    except Exception:
        path = repo_root / "config" / "external_parties.json"
        if not path.exists():
            return []
        return _read_json(path)


def load_user_permissions(repo_root: Path) -> Dict[str, Any]:
    """
    Load user permissions configuration.

    Preferred: config/config.py (repo-level package) if present.
    Fallback: repo_root/config/user_permissions.json
    """
    try:
        from config.config import load_user_permissions as _loader  # type: ignore
        return _loader() or {}
    except Exception:
        path = repo_root / "config" / "user_permissions.json"
        if not path.exists():
            return {}
        data = _read_json(path)
        return data or {}
