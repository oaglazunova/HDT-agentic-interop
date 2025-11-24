from __future__ import annotations
from datetime import datetime, date as _date
from typing import Iterable
import re

_DURATION_RE = re.compile(r"^\d{2}:\d{2}:\d{2}$")

class ValidationError(ValueError):
    pass

def _normalize_iso_datetime(s: str) -> str:
    if not isinstance(s, str):
        raise ValidationError("date must be a string")

    raw = s.strip()
    # Reject trailing Z or explicit offsets to avoid silent tz loss
    if raw.endswith("Z") or "+" in raw[10:] or "-" in raw[11:]:
        raise ValidationError(f"timezone offsets not allowed: {s!r}")

    try:
        dt = datetime.fromisoformat(raw.replace(" ", "T"))
        if len(raw) == 10:
            return dt.date().isoformat()
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        try:
            d = _date.fromisoformat(raw)
            return d.isoformat()
        except Exception:
            raise ValidationError(f"invalid ISO date/datetime: {s!r}")

def _coerce_int(value, *, min_value: int | None = None, name: str = "value") -> int:
    try:
        iv = int(value)
    except Exception:
        raise ValidationError(f"{name} not an integer: {value!r}")
    if min_value is not None and iv < min_value:
        raise ValidationError(f"{name} below minimum {min_value}: {iv}")
    return iv

def _coerce_float_or_none(v):
    if v is None:
        return None
    try:
        return float(v)
    except Exception:
        raise ValidationError(f"not a float: {v!r}")

def _coerce_str_or_none(v):
    if v is None:
        return None
    return str(v)

def _coerce_duration_or_none(v):
    if v is None:
        return None
    s = str(v)
    if not _DURATION_RE.match(s):
        raise ValidationError(f"duration must be HH:MM:SS, got {v!r}")
    return s

def sanitize_walk_record(rec: dict) -> dict:
    """
    Ensures a single walk record has a valid ISO date/datetime string
    and non-negative integer steps. Also coerces optional numeric fields.
    Returns a sanitized copy.
    """
    if not isinstance(rec, dict):
        raise ValidationError("record must be an object")

    out = {}
    # required
    if "date" not in rec:
        raise ValidationError("missing required field: date")
    out["date"] = _normalize_iso_datetime(rec["date"])

    # steps >= 0
    out["steps"] = _coerce_int(rec.get("steps", 0), min_value=0)

    # optional numerics
    out["distance_meters"] = _coerce_float_or_none(rec.get("distance_meters"))
    out["kcalories"]       = _coerce_float_or_none(rec.get("kcalories"))

    # optional duration (string-like)
    out["duration"]        = _coerce_duration_or_none(rec.get("duration"))

    # preserve any extra fields as-is if you want (comment out to be strict)
    for k, v in rec.items():
        if k not in out:
            out[k] = v

    return out

def sanitize_walk_records(records: Iterable[dict], *, strict: bool = True) -> list[dict]:
    if records is None:
        return []
    cleaned = []
    for i, r in enumerate(records):
        try:
            cleaned.append(sanitize_walk_record(r))
        except ValidationError as e:
            if strict:
                raise ValidationError(f"record[{i}]: {e}") from e
            # else: skip / or collect stats
    return cleaned

