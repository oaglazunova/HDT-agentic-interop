"""Wiring for the HDT MCP server.

This module builds the dependency graph:
- settings/env
- optional vault
- adapters + domain service
- policy runtime
- telemetry
- resource/tool registration

Keeping this separated from `server.py` makes `server.py` resilient to
non-standard loaders (e.g., MCP CLI importing by file path).
"""

from __future__ import annotations

import copy
import importlib
import os
import threading
import uuid
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from hdt_mcp.models.behavior import _headers as _base_headers
from hdt_mcp.http.client import (
    cached_get as _http_cached_get,
    hdt_get as _http_hdt_get,
)
from hdt_mcp.observability.telemetry import log_event as _telemetry_log_event
from hdt_mcp.domain.services import HDTService
from hdt_mcp.adapters.api_walk import ApiWalkAdapter
from hdt_mcp.adapters.vault_repo import VaultAdapter
from hdt_mcp.policy_runtime import PolicyRuntime

from .mcp_resources import register_resources
from .mcp_tools import register_tools


class Settings:
    def __init__(
        self,
        *,
        repo_root: Path,
        data_dir: Path,
        config_dir: Path,
        client_id: str,
        api_base: str,
        api_key: str,
        enable_policy_tools: bool,
        telemetry_dir: Path,
        disable_telemetry: bool,
        cache_ttl: int,
        retry_max: int,
        policy_path: Path,
        user_perms_path: Path,
        redact_token: str,
        vault_enable: bool,
        vault_db: Path,
        integrated_tool_name: str,
        website_url: str,
    ):
        self.repo_root = repo_root
        self.data_dir = data_dir
        self.config_dir = config_dir
        self.client_id = client_id
        self.api_base = api_base
        self.api_key = api_key
        self.enable_policy_tools = enable_policy_tools
        self.telemetry_dir = telemetry_dir
        self.disable_telemetry = disable_telemetry
        self.cache_ttl = cache_ttl
        self.retry_max = retry_max
        self.policy_path = policy_path
        self.user_perms_path = user_perms_path
        self.redact_token = redact_token
        self.vault_enable = vault_enable
        self.vault_db = vault_db
        self.integrated_tool_name = integrated_tool_name
        self.website_url = website_url

    @staticmethod
    def from_env() -> "Settings":
        repo_root = Path(__file__).resolve().parents[1]

        # Load .env from repo root
        load_dotenv(repo_root / ".env")

        data_dir = repo_root / "data"
        data_dir.mkdir(parents=True, exist_ok=True)

        config_dir = repo_root / "config"

        client_id = os.getenv("MCP_CLIENT_ID", "MODEL_DEVELOPER_1")
        api_base = os.environ.get("HDT_API_BASE", "http://localhost:5000")
        api_key = os.environ.get("HDT_API_KEY", os.environ.get("MODEL_DEVELOPER_1_API_KEY", ""))

        enable_policy_tools = (os.getenv("HDT_ENABLE_POLICY_TOOLS", "0") or "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

        telemetry_dir = Path(os.getenv("HDT_TELEMETRY_DIR", str(repo_root / "hdt_mcp" / "telemetry")))
        telemetry_dir.mkdir(parents=True, exist_ok=True)
        disable_telemetry = os.getenv("HDT_DISABLE_TELEMETRY", "0").lower() in ("1", "true", "yes")

        cache_ttl = int(os.getenv("HDT_CACHE_TTL", "15"))
        retry_max = int(os.getenv("HDT_RETRY_MAX", "2"))

        policy_path = Path(os.getenv("HDT_POLICY_PATH", str(config_dir / "policy.json")))
        user_perms_path = config_dir / "user_permissions.json"
        redact_token = os.getenv("HDT_REDACT_TOKEN", "***redacted***")

        vault_enable = os.getenv("HDT_VAULT_ENABLE", "0").lower() in ("1", "true", "yes")
        vault_db = Path(os.getenv("HDT_VAULT_DB", str(data_dir / "lifepod.duckdb")))

        integrated_tool_name = os.getenv("HDT_INTEGRATED_TOOL_NAME", "vault.integrated@v1")
        website_url = os.getenv(
            "HDT_WEBSITE_URL",
            "https://github.com/oaglazunova/HDT-agentic-interop",
        )

        return Settings(
            repo_root=repo_root,
            data_dir=data_dir,
            config_dir=config_dir,
            client_id=client_id,
            api_base=api_base,
            api_key=api_key,
            enable_policy_tools=enable_policy_tools,
            telemetry_dir=telemetry_dir,
            disable_telemetry=disable_telemetry,
            cache_ttl=cache_ttl,
            retry_max=retry_max,
            policy_path=policy_path,
            user_perms_path=user_perms_path,
            redact_token=redact_token,
            vault_enable=vault_enable,
            vault_db=vault_db,
            integrated_tool_name=integrated_tool_name,
            website_url=website_url,
        )


_request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)


def _new_request_id() -> str:
    return uuid.uuid4().hex


def _get_request_id() -> str:
    rid = _request_id_ctx.get()
    if not rid:
        rid = _new_request_id()
        _request_id_ctx.set(rid)
    return rid


def _set_request_id(rid: str | None) -> None:
    if rid:
        _request_id_ctx.set(rid)


def _resolve_vault_module():
    # Resolve dynamically to avoid hard import errors when vault is absent.
    for name in ("HDT_VAULT.vault", "hdt_mcp.vault"):
        try:
            return importlib.import_module(name)
        except Exception:
            continue
    return None


def build_mcp(*, settings: Settings | None = None) -> tuple[FastMCP, Settings]:
    """Build the FastMCP server + settings."""

    st = settings or Settings.from_env()

    def headers_provider() -> dict[str, str]:
        base = dict(_base_headers())
        base["X-Request-Id"] = _get_request_id()
        # Forward API key if you use it server-side
        if st.api_key:
            base.setdefault("Authorization", f"Bearer {st.api_key}")
        return base

    # Optional vault
    vault_mod = _resolve_vault_module()
    if st.vault_enable and vault_mod is not None:
        try:
            vault_mod.init(db_path=str(st.vault_db))
        except Exception:
            vault_mod = None

    vault_repo = VaultAdapter(vault_mod) if (st.vault_enable and vault_mod is not None) else None

    # Adapters + domain
    walk_adapter = ApiWalkAdapter(base_url=st.api_base, headers_provider=headers_provider)
    domain = HDTService(walk_source=walk_adapter, vault=vault_repo)

    # Policy runtime
    policy = PolicyRuntime(policy_path=st.policy_path, user_permissions_path=st.user_perms_path, redact_token=st.redact_token)

    # Telemetry logger closure
    def log_event(kind: str, name: str, args: dict | None = None, ok: bool = True, ms: int = 0, *, client_id: str | None = None, corr_id: str | None = None) -> None:
        _telemetry_log_event(
            dir_path=st.telemetry_dir,
            disabled=st.disable_telemetry,
            kind=kind,
            name=name,
            args=args,
            ok=ok,
            ms=ms,
            client_id=(client_id or st.client_id),
            corr_id=corr_id,
            get_request_id=_get_request_id,
        )

    # HTTP wrappers (cached)
    cache: dict[tuple[str, tuple], tuple[float, dict]] = {}
    cache_lock = threading.Lock()

    def hdt_get(path: str, params: dict | None = None) -> dict:
        return _http_hdt_get(
            base_url=st.api_base,
            path=path,
            params=params,
            headers_provider=headers_provider,
            retry_max=st.retry_max,
            get_request_id=_get_request_id,
            set_request_id=_set_request_id,
        )

    def cached_get(path: str, params: dict | None = None) -> dict:
        return _http_cached_get(
            cache=cache,
            cache_lock=cache_lock,
            cache_ttl=st.cache_ttl,
            base_url=st.api_base,
            path=path,
            params=params,
            headers_provider=headers_provider,
            retry_max=st.retry_max,
            get_request_id=_get_request_id,
            set_request_id=_set_request_id,
        )

    # Build MCP instance
    mcp = FastMCP(
        name="HDT-MCP",
        instructions="Façade exposing HDT data & decisions as MCP tools/resources.",
        website_url=st.website_url,
    )

    # Tool registry list for registry://tools
    tool_registry: list[dict[str, Any]] = [
        {"name": "hdt.walk.stream@v1", "args": ["user_id", "prefer", "start", "end"]},
        {"name": "hdt.walk.stats@v1", "args": ["user_id", "start", "end"]},
        {"name": "healthz@v1", "args": []},
        {"name": "hdt.get_trivia_data@v1", "args": ["user_id"]},
        {"name": "hdt.get_sugarvita_data@v1", "args": ["user_id"]},
        {"name": "hdt.get_sugarvita_player_types@v1", "args": ["user_id", "purpose"]},
        {"name": "hdt.get_health_literacy_diabetes@v1", "args": ["user_id", "purpose"]},
        {"name": "behavior_strategy@v1", "args": ["user_id", "purpose"]},
        {"name": "intervention_time@v1", "args": []},
    ]
    if st.enable_policy_tools:
        tool_registry.extend(
            [
                {"name": "policy.evaluate@v1", "args": ["purpose", "client_id", "tool"]},
                {"name": "consent.status@v1", "args": ["client_id"]},
                {"name": "policy.reload@v1", "args": []},
            ]
        )
    tool_registry.append({"name": "vault.maintain@v1", "args": ["days"]})

    register_resources(
        mcp,
        config_dir=st.config_dir,
        telemetry_dir=st.telemetry_dir,
        domain=domain,
        policy=policy,
        client_id=st.client_id,
        integrated_tool_name=st.integrated_tool_name,
        tool_registry=tool_registry,
        log_event=log_event,
    )

    register_tools(
        mcp,
        domain=domain,
        cached_get=cached_get,
        policy=policy,
        log_event=log_event,
        vault=(vault_mod if (st.vault_enable and vault_mod is not None) else None),
        vault_enabled=st.vault_enable,
        client_id=st.client_id,
        enable_policy_tools=st.enable_policy_tools,
    )

    return mcp, st


def run(mcp: FastMCP) -> None:
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    mcp.run(transport=transport)
