import os
import logging
import functools
import inspect
from typing import Callable, TypeVar, ParamSpec
from mcp.server.fastmcp import FastMCP

from .governor import HDTGovernor
from .policy.engine import apply_policy, apply_policy_safe, policy_last_meta
from hdt_common.tooling import (
    InstrumentConfig,
    PolicyConfig,
    instrument_async_tool,
    instrument_sync_tool,
)
from hdt_common.telemetry import telemetry_recent
from hdt_config.settings import init_runtime
from hdt_mcp.policy.engine import explain_policy


logger = logging.getLogger(__name__)

mcp = FastMCP(
    name="HDT-MCP-OptionD",
    instructions="External-facing HDT MCP server (Option D). Delegates to HDTGovernor which calls Sources MCP.",
)

gov = HDTGovernor()

MCP_CLIENT_ID = os.getenv("MCP_CLIENT_ID", "MODEL_DEVELOPER_1")
LANES = {"analytics", "modeling", "coaching"}

_POLICY_CFG = PolicyConfig(
    lanes=LANES,
    apply_policy=apply_policy,
    apply_policy_safe=apply_policy_safe,
    policy_last_meta=policy_last_meta,
)

P = ParamSpec("P")
R = TypeVar("R")

def _cfg(tool_name: str) -> InstrumentConfig:
    return InstrumentConfig(
        kind="tool",
        name=tool_name,
        client_id=MCP_CLIENT_ID,
        new_corr_id_per_call=True,
    )

def _instrument(tool_name: str):
    return instrument_async_tool(_cfg(tool_name), policy=_POLICY_CFG)


def hdt_tool(name: str, *, sync: bool = False, instrument: bool = True):
    """
    Registers an MCP tool and applies instrumentation (+ policy for async).
    Keeps tool signature stable for MCP schema generation.
    """
    def decorator(fn: Callable[P, R]) -> Callable[P, R]:
        sig = inspect.signature(fn)

        wrapped = fn
        if instrument:
            wrapped = instrument_sync_tool(_cfg(name))(wrapped) if sync else _instrument(name)(wrapped)

        # Defensive: keep signature even if wrappers change
        registered = mcp.tool(name=name)(wrapped)
        try:
            registered.__signature__ = sig  # type: ignore[attr-defined]
        except Exception:
            pass
        return registered

    return decorator

# All domain tools must delegate to HDTGovernor; gateway contains no domain logic
def delegate_to_gov(method_name: str):
    """
    Replaces tool implementation with a call to gov.<method_name>(**bound_args),
    filtering out extra tool params not accepted by the gov method.
    """
    def decorator(fn):
        tool_sig = inspect.signature(fn)

        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            bound = tool_sig.bind(*args, **kwargs)
            bound.apply_defaults()

            method = getattr(gov, method_name)
            method_sig = inspect.signature(method)

            accepts_varkw = any(
                p.kind == inspect.Parameter.VAR_KEYWORD
                for p in method_sig.parameters.values()
            )

            if accepts_varkw:
                call_kwargs = dict(bound.arguments)
            else:
                allowed = set(method_sig.parameters.keys())
                call_kwargs = {k: v for k, v in bound.arguments.items() if k in allowed}

            return await method(**call_kwargs)

        # Preserve schema signature for MCP
        try:
            wrapper.__signature__ = tool_sig  # type: ignore[attr-defined]
        except Exception:
            pass

        return wrapper

    return decorator


@hdt_tool("hdt.healthz.v1", sync=True)  # set instrument=False if you want no telemetry here
def hdt_healthz() -> dict:
    return {"ok": True}


@hdt_tool("hdt.sources.status.v1")
@delegate_to_gov("sources_status")
async def hdt_sources_status(
    user_id: int,
    purpose: str = "analytics",  # kept for lane validation + consistent auditing; governor ignores it
) -> dict:
    ...


@hdt_tool("hdt.walk.fetch.v1")
@delegate_to_gov("fetch_walk")
async def hdt_walk_fetch(
    user_id: int,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
    prefer: str = "gamebus",
    prefer_data: str = "auto",
    purpose: str = "analytics",
) -> dict:
    ...



@hdt_tool("hdt.trivia.fetch.v1")
@delegate_to_gov("fetch_trivia")
async def hdt_trivia_fetch(
    user_id: int,
    start_date: str | None = None,
    end_date: str | None = None,
    purpose: str = "analytics",
) -> dict:
    ...


@hdt_tool("hdt.sugarvita.fetch.v1")
@delegate_to_gov("fetch_sugarvita")
async def hdt_sugarvita_fetch(
    user_id: int,
    start_date: str | None = None,
    end_date: str | None = None,
    purpose: str = "analytics",
) -> dict:
    ...


@hdt_tool("hdt.walk.features.v1")
@delegate_to_gov("walk_features")
async def hdt_walk_features(
    user_id: int,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
    prefer: str = "gamebus",
    prefer_data: str = "auto",
    purpose: str = "modeling",
) -> dict:
    ...

# internal (non-governor), still goes through instrumentation + policy for consistency
@hdt_tool("hdt.policy.explain.v1")
async def hdt_policy_explain(tool: str, purpose: str = "analytics") -> dict:
    return explain_policy(purpose, tool, client_id=MCP_CLIENT_ID)


# internal (non-governor), still instrumented for auditing; payload already redacted on read
@hdt_tool("hdt.telemetry.recent.v1")
async def hdt_telemetry_recent(n: int = 50, purpose: str = "analytics") -> dict:
    return telemetry_recent(n=n)


def main() -> None:
    # Entry points (console_scripts) call main() directly, so we must perform
    # runtime initialization here (dotenv + logging).
    init_runtime()
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    mcp.run(transport=transport)


if __name__ == "__main__":
    main()
