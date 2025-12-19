from __future__ import annotations
from typing import TypedDict, List, Optional
import os
from datetime import datetime, timedelta, timezone

# Optional: read from vault if available
try:
    from hdt_mcp import vault_store as _vault
except Exception:
    _vault = None


def _vault_enabled() -> bool:
    """
    Evaluate the vault enable flag at call time, not import time.
    This allows tests (and runtime) to toggle HDT_VAULT_ENABLE dynamically.
    """
    return os.getenv("HDT_VAULT_ENABLE", "0").lower() in ("1", "true", "yes")

# Optional API fallback (same envs you already use)
HDT_API_BASE = os.environ.get("HDT_API_BASE", "http://localhost:5000")
HDT_API_KEY  = os.environ.get("HDT_API_KEY", os.environ.get("MODEL_DEVELOPER_1_API_KEY", ""))

class BehaviorPlan(TypedDict):
    message: str
    bct_refs: List[str]
    avg_steps: int
    days_considered: int
    rationale: str

def _headers() -> dict:
    if not HDT_API_KEY:
        return {}
    return {
        # Canonical header: prefer Authorization: Bearer
        "Authorization": f"Bearer {HDT_API_KEY}",
    }

def _fetch_walk_via_api(user_id: int) -> list[dict]:
    """Fallback: query your Flask API."""
    import requests
    url = f"{HDT_API_BASE.rstrip('/')}/get_walk_data"
    r = requests.get(url, headers=_headers(), params={"user_id": user_id}, timeout=20)
    r.raise_for_status()
    data = r.json()
    # normalize to an envelope list
    envelopes = data if isinstance(data, list) else [data]
    leaf = next((e for e in envelopes if str(e.get("user_id")) == str(user_id)), None) or {}
    return leaf.get("data") or leaf.get("records") or []

def _parse_date(d: str) -> Optional[datetime]:
    try:
        # Accept "YYYY-MM-DD" or ISO with time
        return datetime.fromisoformat(d.split("T")[0])
    except Exception:
        return None

def _avg_steps_last_days(records: list[dict], days: int = 7) -> int:
    if not records:
        return 0
    cutoff = datetime.now(timezone.utc).date() - timedelta(days=days - 1)
    vals: list[int] = []
    for r in records:
        dt = _parse_date(str(r.get("date", "")))
        if not dt:
            continue
        if dt.date() >= cutoff:
            try:
                vals.append(int(r.get("steps") or 0))
            except Exception:
                pass
    if not vals:
        return 0
    return int(round(sum(vals) / len(vals)))

# TODO: add a llm_client.py and replace _pick_message with an LLM call, but keep the same output keys
def _pick_message(avg_steps: int) -> tuple[str, list[str], str]:
    """
    Super-simple rule-of-thumb coach:
      <3000: activation + prompts
      3000..6999: habit formation + planning
      >=7000: reinforce + graded tasks to reach 8–9k
    Returns (message, BCT refs, rationale)
    """
    if avg_steps < 3000:
        return (
            "Let’s spark movement: add two 10-minute walks today. I’ll nudge you after lunch and early evening.",
            ["1.4 Action planning", "7.1 Prompts/cues", "8.3 Habit formation"],
            "Low recent activity—short, scheduled bouts are easier to start."
        )
    if avg_steps < 7000:
        return (
            "You’re on the move! Plan one 15-minute walk after dinner and take stairs when possible.",
            ["1.2 Problem solving", "1.4 Action planning", "8.1 Behavioral practice"],
            "Moderate activity—structured small upgrades build habit strength."
        )
    return (
        "Great consistency. Try one extra 1–2k steps mid-afternoon this week—keep it light and enjoyable.",
        ["8.7 Graded tasks", "10.4 Social reward", "2.2 Feedback on behavior"],
        "High baseline—graded progression maintains motivation safely."
    )

def behavior_strategy(user_id: int, days: int = 7) -> BehaviorPlan:
    """
    Minimal “LLM-lite” strategy: compute avg steps over recent days,
    pick a short COM-B/BCT grounded suggestion.
    """
    records: list[dict] = []
    # Prefer vault
    if _vault_enabled() and _vault is not None:
        try:
            records = _vault.read_walk_records(int(user_id)) or []
        except Exception:
            records = []
    # Fallback to API
    if not records:
        try:
            records = _fetch_walk_via_api(int(user_id)) or []
        except Exception:
            records = []

    avg_steps = _avg_steps_last_days(records, days=days)
    message, bcts, why = _pick_message(avg_steps)

    return {
        "message": message,
        "bct_refs": bcts,
        "avg_steps": int(avg_steps),
        "days_considered": int(days),
        "rationale": why,
    }
