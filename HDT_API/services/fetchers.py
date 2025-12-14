from typing import TypedDict, Optional, List, Dict
from datetime import date, timedelta
import os

class FetcherResult(TypedDict):
    records: List[Dict]
    total: Optional[int]  # None if unknown/expensive

# env flag: asc (oldest→newest) or desc (newest→oldest)
_WALK_ORDER = os.getenv("HDT_WALK_ORDER", "asc").strip().lower()
_DESC = (_WALK_ORDER == "desc")

def _sort_records_by_date(rows: List[Dict]) -> List[Dict]:
    """
    Deterministically sort by 'date'.
    - Works for 'YYYY-MM-DD' and ISO date-times (we strip trailing 'Z').
    - Records without 'date' are kept at the end, in original order.
    """
    with_date = [r for r in rows if isinstance(r.get("date"), str)]
    without_date = [r for r in rows if not isinstance(r.get("date"), str)]

    # Normalize for lexicographic sort
    def _key(rec: Dict) -> str:
        return rec["date"].replace("Z", "")

    with_date.sort(key=_key, reverse=_DESC)
    return with_date + without_date

def _normalize_iso_key(s: str) -> str:
    """
    Normalize a date/date-time string to a comparable ISO key:
    - remove trailing 'Z'
    - expand date-only (YYYY-MM-DD) to start-of-day time to allow lexicographic compare
    """
    s = s.replace("Z", "")
    if "T" not in s:
        s = f"{s}T00:00:00"
    return s


def fetch_walk_batch(
    user_id: int,
    limit: int,
    offset: int,
    from_iso: Optional[str] = None,
    to_iso: Optional[str] = None,
) -> FetcherResult:
    # Local import to avoid circulars
    from .app import get_connected_app_info
    app_name, player_id, auth_bearer = get_connected_app_info(user_id, "walk_data")
    app_norm = (app_name or "").strip().lower()

    # Provider fetchers
    from ..providers.gamebus.walk import fetch_walk_data_gamebus as gb_fetch
    from ..providers.google_fit.walk import fetch_walk_data_google_fit as gf_fetch

    records: List[Dict] = []
    total: Optional[int] = None

    if app_norm == "gamebus":
        # If GameBus supports server-side order+paging, prefer that (faster).
        # Otherwise: fetch all -> sort -> slice.
        all_rows = gb_fetch(player_id, auth_bearer=auth_bearer) or []
        # Optional window filtering
        if from_iso or to_iso:
            fkey = _normalize_iso_key(from_iso) if from_iso else None
            tkey = _normalize_iso_key(to_iso) if to_iso else None
            filtered: List[Dict] = []
            for r in all_rows:
                d = r.get("date")
                if not isinstance(d, str):
                    continue
                k = _normalize_iso_key(d)
                if fkey and k < fkey:
                    continue
                if tkey and k > tkey:
                    continue
                filtered.append(r)
            all_rows = filtered
        all_rows = _sort_records_by_date(all_rows)
        total = len(all_rows)
        records = all_rows[offset: offset + limit]

    elif app_norm in ("google fit", "googlefit", "google_fit"):
        all_rows = gf_fetch(player_id, auth_bearer=auth_bearer) or []
        if from_iso or to_iso:
            fkey = _normalize_iso_key(from_iso) if from_iso else None
            tkey = _normalize_iso_key(to_iso) if to_iso else None
            filtered = []
            for r in all_rows:
                d = r.get("date")
                if not isinstance(d, str):
                    continue
                k = _normalize_iso_key(d)
                if fkey and k < fkey:
                    continue
                if tkey and k > tkey:
                    continue
                filtered.append(r)
            all_rows = filtered
        all_rows = _sort_records_by_date(all_rows)
        total = len(all_rows)
        records = all_rows[offset: offset + limit]

    elif app_norm.startswith("placeholder"):
        if os.getenv("HDT_ALLOW_PLACEHOLDER_MOCKS", "0").lower() in ("1", "true", "yes"):
            today = date.today()
            all_rows = [
                {"date": (today - timedelta(days=2)).isoformat(), "steps": 4231},
                {"date": (today - timedelta(days=1)).isoformat(), "steps": 6120},
                {"date": today.isoformat(),                        "steps": 3580},
            ]
            if from_iso or to_iso:
                fkey = _normalize_iso_key(from_iso) if from_iso else None
                tkey = _normalize_iso_key(to_iso) if to_iso else None
                filtered = []
                for r in all_rows:
                    d = r.get("date")
                    if not isinstance(d, str):
                        continue
                    k = _normalize_iso_key(d)
                    if fkey and k < fkey:
                        continue
                    if tkey and k > tkey:
                        continue
                    filtered.append(r)
                all_rows = filtered
            all_rows = _sort_records_by_date(all_rows)
            total = len(all_rows)
            records = all_rows[offset: offset + limit]
        else:
            total = 0
            records = []
    else:
        total = 0
        records = []

    return {"records": records, "total": total}
