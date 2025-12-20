from datetime import datetime, date as _date
import re

_DURATION_RE = re.compile(r"^\d{2}:\d{2}:\d{2}$")

class ValidationError(ValueError):
    pass

def _normalize_iso_datetime(s):
    # Expect a string input under Python 3
    if not isinstance(s, str):
        raise ValidationError("date must be a string")

    raw = s.strip()
    # Reject trailing Z or explicit offsets to avoid silent tz loss
    # Keep the same windowing as the original: after date portion
    if raw.endswith("Z") or ("+" in raw[10:]) or ("-" in raw[11:]):
        raise ValidationError("timezone offsets not allowed: {0!r}".format(s))

    # Try datetime first: both "YYYY-MM-DD HH:MM:SS" and "YYYY-MM-DDTHH:MM:SS"
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(raw, fmt)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            pass

    # Then try date-only "YYYY-MM-DD"
    try:
        d = datetime.strptime(raw, "%Y-%m-%d").date()
        return d.isoformat()
    except Exception:
        raise ValidationError("invalid ISO date/datetime: {0!r}".format(s))

def _coerce_int(value, min_value=None, name="value"):
    try:
        iv = int(value)
    except Exception:
        raise ValidationError("{0} not an integer: {1!r}".format(name, value))
    if min_value is not None and iv < min_value:
        raise ValidationError("{0} below minimum {1}: {2}".format(name, min_value, iv))
    return iv

def _coerce_float_or_none(v):
    if v is None:
        return None
    try:
        return float(v)
    except Exception:
        raise ValidationError("not a float: {0!r}".format(v))

def _coerce_str_or_none(v):
    if v is None:
        return None
    return str(v)

def _coerce_duration_or_none(v):
    if v is None:
        return None
    s = str(v)
    if not _DURATION_RE.match(s):
        raise ValidationError("duration must be HH:MM:SS, got {0!r}".format(v))
    return s

def sanitize_walk_record(rec):
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

def sanitize_walk_records(records, strict=True):
    if records is None:
        return []
    cleaned = []
    for i, r in enumerate(records):
        try:
            cleaned.append(sanitize_walk_record(r))
        except ValidationError as e:
            if strict:
                # Python 2 does not support exception chaining
                raise ValidationError("record[{0}]: {1}".format(i, e))
            # else: skip / or collect stats
    return cleaned

