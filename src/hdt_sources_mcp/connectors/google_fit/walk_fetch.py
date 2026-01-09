import logging
import os
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from hdt_sources_mcp.connectors.google_fit.walk_parse import parse_google_fit_walk_data
from hdt_sources_mcp.core_infrastructure.http_client import DEFAULT_HTTP_CLIENT


logger = logging.getLogger(__name__)

GOOGLE_FIT_ENDPOINT_TEMPLATE = (
    "https://www.googleapis.com/fitness/v1/users/{player_id}/dataSources/"
    "derived:com.google.step_count.delta:com.google.android.gms:merge_step_deltas/"
    "datasets/{start_time}-{end_time}"
)


def _auth_headers(auth_bearer: str | None) -> dict[str, str]:
    if not auth_bearer:
        return {}
    t = str(auth_bearer).strip()
    if not t.lower().startswith("bearer "):
        t = f"Bearer {t}"
    return {"Authorization": t}


def _parse_datetime_loose(s: str, *, tz: ZoneInfo) -> datetime:
    """Parse a date/time string.

    Accepts:
      - YYYY-MM-DD
      - YYYY-MM-DD HH:MM:SS
      - ISO timestamps with or without timezone (Z / +00:00)

    Naive timestamps are interpreted in the provided timezone.
    """
    st = s.strip()
    if len(st) == 10 and st[4] == "-" and st[7] == "-":
        dt = datetime.fromisoformat(st)
        return dt.replace(tzinfo=tz)
    if " " in st and "T" not in st:
        dt = datetime.strptime(st, "%Y-%m-%d %H:%M:%S")
        return dt.replace(tzinfo=tz)
    dt = datetime.fromisoformat(st.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    return dt


def _to_nanos(dt: datetime) -> int:
    return int(dt.astimezone(timezone.utc).timestamp() * 1e9)


def fetch_google_fit_walk_data(
    player_id,
    auth_bearer,
    start_time=0,
    end_time=4102444800000000000,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
):
    """
    Fetch step count data from Google Fit and parse it.

    Backward compatible:
    - If you pass start_time/end_time nanos, it works as before.
    - If you pass start_date/end_date, it converts those to nanos.

    Important:
    - By default this applies a safety window of the last 365 days when called with
      the historical 'all data' defaults. Set HDT_GOOGLE_FIT_DEFAULT_DAYS=0 to disable.
    """
    tz_key = os.getenv("HDT_TZ", "Europe/Amsterdam")
    try:
        tz = ZoneInfo(tz_key)
    except (ZoneInfoNotFoundError, ModuleNotFoundError):
        logger.warning("ZoneInfo '%s' not available; falling back to UTC (install tzdata or set HDT_TZ=UTC).", tz_key)
        tz = timezone.utc

    if start_date or end_date:
        if start_date:
            start_time = _to_nanos(_parse_datetime_loose(start_date, tz=tz))
        if end_date:
            end_time = _to_nanos(_parse_datetime_loose(end_date, tz=tz))

    # Safety default: avoid “fetch everything since epoch” unless explicitly disabled
    try:
        default_days = int(os.getenv("HDT_GOOGLE_FIT_DEFAULT_DAYS", "365"))
    except Exception:
        default_days = 365

    if (start_time == 0 and int(end_time) >= 4_000_000_000_000_000_000 and default_days > 0):
        now = datetime.now(tz=tz)
        start_time = _to_nanos(now - timedelta(days=default_days))
        end_time = _to_nanos(now)
        logger.info("Google Fit default window applied: last %s days", default_days)

    headers = _auth_headers(auth_bearer)
    url = GOOGLE_FIT_ENDPOINT_TEMPLATE.format(player_id=player_id, start_time=int(start_time), end_time=int(end_time))

    try:
        raw_data = DEFAULT_HTTP_CLIENT.get_json(url, headers=headers)
        return parse_google_fit_walk_data(raw_data)
    except Exception as e:
        logger.error("Error fetching Google Fit walk data for player %s: %s", player_id, e)
        return None
