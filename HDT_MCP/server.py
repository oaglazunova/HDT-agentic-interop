from typing import Literal, TypedDict
import os
import json
import requests
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()

# Your existing API that the MCP façade talks to (your Flask/whatever service).
HDT_API_BASE = os.environ.get("HDT_API_BASE", "http://localhost:5000")
# If your API uses a key/header, grab it from env. Adjust header name if needed.
HDT_API_KEY  = os.environ.get("HDT_API_KEY", os.environ.get("MODEL_DEVELOPER_1_API_KEY", ""))  # reuse your .env

# Create the MCP server façade (B0: MCP Core / Orchestrator)
mcp = FastMCP(
    name="HDT-MCP",
    instructions="Façade exposing HDT data & decisions as MCP tools/resources.",
    website_url="https://github.com/oaglazunova/Interoperable-and-modular-HDT-system-prototype",
)


# --- helpers ----------------------------------------------------------------

def _hdt_get(path: str, params: dict | None=None) -> dict:
    url = f"{HDT_API_BASE}{path}"
    headers = {}
    if HDT_API_KEY:
        headers["X-API-KEY"] = HDT_API_KEY
    r = requests.get(url, headers=headers, params=params or {}, timeout=60)
    r.raise_for_status()
    return r.json()


# ---------- RESOURCES (context / “read-only”) ----------
# Resources are things the agent can "open" for context, like files/URIs.

@mcp.resource("vault://user/{user_id}/integrated")
def get_integrated_view(user_id: str) -> dict:
    """
    Integrated HDT View (VG in the diagram). Minimal “Integrated HDT View” resource from your local storage file.
    Extend to unify multiple stores over time.
    For now, we read from the local JSON store; later, swap to the real vault.
    """
    try:
        with open("diabetes_pt_hl_storage.json", "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        data = {}
    return {"user_id": user_id, "integrated": data.get(user_id) or data}

@mcp.resource("hdt://{user_id}/sources")
def list_sources(user_id: str) -> dict:
    """Expose connected sources for a user (which adapters are active) (DH).
    (what the README calls out in config/users.json)."""
    try:
        with open("config/users.json", "r", encoding="utf-8") as f:
            users = json.load(f)
    except FileNotFoundError:
        users = {}
    return {"user_id": user_id, "sources": users.get(user_id, {})}


# --- 2) TOOLS (actions / compute) -------------------------------------------
# Tools are callables with typed params; MCP auto-generates JSON Schemas (B1).

@mcp.tool(name="hdt.get_trivia_data@v1")
def tool_get_trivia_data(user_id: str) -> dict:
    """Wraps /get_trivia_data endpoint."""
    return _hdt_get("/get_trivia_data", {"user_id": user_id})

@mcp.tool(name="hdt.get_sugarvita_data@v1")
def tool_get_sugarvita_data(user_id: str) -> dict:
    """Wraps /get_sugarvita_data endpoint."""
    return _hdt_get("/get_sugarvita_data", {"user_id": user_id})

@mcp.tool(name="hdt.get_walk_data@v1")
def tool_get_walk_data(user_id: str) -> dict:
    """Wraps /get_walk_data endpoint."""
    return _hdt_get("/get_walk_data", {"user_id": user_id})


# --- 3) “Model Hub” placeholders (M1/M2) ------------------------------------
# Kept lightweight (no LLM). You can replace these with real models later.

class Strategy(TypedDict):
    stage: Literal[
        "precontemplation",
        "contemplation",
        "preparation",
        "action",
        "maintenance",
    ]
    com_b_focus: list[Literal["Capability", "Opportunity", "Motivation"]]
    suggestions: list[str]
    bct_refs: list[str]

@mcp.tool(name="behavior_strategy@v1")
def behavior_strategy(
    stage: Literal[
        "precontemplation",
        "contemplation",
        "preparation",
        "action",
        "maintenance",
    ],
    com_b_focus: list[str] = []
) -> Strategy:
    """
    Toy COM-B/TTM policy engine to prove the façade path from C2→MH works.
    """
    base = {
        "precontemplation": (["Increase awareness of benefits", "Prompt self-reflection"], ["5.1","5.3","1.1"]),
        "contemplation":    (["Weigh pros/cons", "Draft if-then plans"], ["1.2","1.4","1.2"]),
        "preparation":      (["Set graded tasks", "Action planning with cues"], ["1.4","8.7","7.1"]),
        "action":           (["Problem solve barriers", "Schedule social support"], ["1.2","3.1","3.2"]),
        "maintenance":      (["Relapse prevention", "Review behavior goals"], ["1.2","1.5","8.3"]),
    }
    sug, bct = base[stage]
    if "Capability" in com_b_focus:  sug += ["Instruction: how to perform behavior"]
    if "Opportunity" in com_b_focus: sug += ["Restructure environment (physical/social)"]
    if "Motivation" in com_b_focus:  sug += ["Identity salience & reinforcement schedule"]
    # de-dup suggestions while preserving order
    seen, dedup = set(), []
    for s in sug:
        if s not in seen:
            seen.add(s); dedup.append(s)
    return {"stage": stage, "com_b_focus": com_b_focus, "suggestions": dedup, "bct_refs": bct}


class TimingPlan(TypedDict):
    next_window_local: str
    rationale: str

@mcp.tool(name="intervention_time@v1")
def intervention_time(local_tz: str = "Europe/Amsterdam",
                      preferred_hours: tuple[int, int] = (18, 21),
                      min_gap_hours: int = 6,
                      last_prompt_iso: str | None = None) -> TimingPlan:
    """
    Simple heuristic that returns an evening window; replace with analytics later.
    """
    # (You could also read recent activity from your adapters and tailor this.)
    start, end = preferred_hours
    return {
        "next_window_local": f"today {start:02d}:00–{end:02d}:00 {local_tz}",
        "rationale": f"Respect ≥{min_gap_hours}h gap; evening adherence tendency."
    }

# --- 4) Entrypoint / Transport ---------------------------------------------

def main():
    """
    Run the MCP server using either stdio (great for local dev) or streamable-http
    (handy for desktop agents / remote clients). Choose via MCP_TRANSPORT env var.
    """
    transport = os.environ.get("MCP_TRANSPORT", "stdio")  # "stdio" or "streamable-http"
    mcp.run(transport=transport)

if __name__ == "__main__":
    main()
