from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv


def _find_repo_root(start: Path) -> Optional[Path]:
    """
    Walk upward until we find pyproject.toml or .git.
    This stays correct if you later introduce src/ or move files.
    """
    start = start.resolve()
    for p in (start, *start.parents):
        if (p / "pyproject.toml").exists() or (p / ".git").exists():
            return p
    return None


@lru_cache(maxsize=1)
def repo_root() -> Path:
    """Best-effort repository root discovery.

    Order of precedence:
      1) HDT_REPO_ROOT (explicit override)
      2) walk upward from current working directory
      3) walk upward from this module file's directory
    """
    explicit = os.getenv("HDT_REPO_ROOT")
    if explicit:
        p = Path(explicit).expanduser()
        try:
            p = p.resolve()
        except Exception:
            p = p.absolute()

        if not p.exists() or not p.is_dir():
            raise RuntimeError(f"HDT_REPO_ROOT does not exist or is not a directory: {p}")

        # Optional but strongly recommended sanity check
        if not ((p / "pyproject.toml").exists() or (p / ".git").exists()):
            # Not fatal, but warn via logging if you prefer
            pass

        return p

    # 1) Search upward from current working directory
    cwd = Path.cwd().resolve()
    root = _find_repo_root(cwd)
    if root:
        return root

    # 2) Derive from module location (use directory, not file path)
    here_dir = Path(__file__).resolve().parent
    root = _find_repo_root(here_dir)
    if root:
        return root

    # Fallback: typical layout (repo/src/hdt_config/settings.py)
    if len(here_dir.parents) >= 2:
        # here_dir is .../src/hdt_config, parents[0]=.../src, parents[1]=.../repo
        return here_dir.parents[1]

    return cwd




@lru_cache(maxsize=1)
def load_env_once() -> Optional[Path]:
    """
    Load dotenv exactly once. Precedence:
      1) HDT_ENV_FILE (explicit path)
      2) repo-root/.env
      3) repo-root/config/.env   (legacy)
    """
    explicit = os.getenv("HDT_ENV_FILE")
    candidates = []

    if explicit:
        candidates.append(Path(explicit).expanduser())
    candidates.append(repo_root() / ".env")
    candidates.append(repo_root() / "config" / ".env")

    for p in candidates:
        try:
            p = p.resolve()
        except Exception:
            continue
        if p.exists() and p.is_file():
            # Do NOT override already-set environment variables
            load_dotenv(dotenv_path=str(p), override=False)
            return p

    return None


@lru_cache(maxsize=1)
def config_dir() -> Path:
    """
    Canonical config folder containing policy.json, users.json, etc.
    Override with HDT_CONFIG_DIR.
    """
    p = os.getenv("HDT_CONFIG_DIR")
    if p:
        return Path(p).expanduser().resolve()
    return (repo_root() / "config").resolve()


def policy_path() -> Path:
    """
    Default policy path. Override with HDT_POLICY_PATH.
    """
    p = os.getenv("HDT_POLICY_PATH")
    if p:
        return Path(p).expanduser().resolve()
    return (config_dir() / "policy.json").resolve()


def telemetry_dir() -> Path:
    """
    Default telemetry dir. Override with HDT_TELEMETRY_DIR.
    """
    p = os.getenv("HDT_TELEMETRY_DIR")
    if p:
        return Path(p).expanduser().resolve()
    return (repo_root() / "artifacts" / "telemetry").resolve()


def configure_logging() -> None:
    """
    Configure logging explicitly. No import-time side effects.
    Idempotent: if logging is already configured, do nothing.
    """
    root = logging.getLogger()
    if root.handlers:
        return

    level_name = os.getenv("HDT_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    fmt = os.getenv(
        "HDT_LOG_FORMAT",
        "%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    logging.basicConfig(level=level, format=fmt)


def init_runtime(*, configure_logs: bool = True, load_env: bool = True) -> None:
    """
    Call this from entrypoints only (servers, scripts).
    """
    if load_env:
        load_env_once()
    if configure_logs:
        configure_logging()
