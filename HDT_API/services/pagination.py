from __future__ import annotations
from flask import request
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

DEFAULT_LIMIT = 200
MAX_LIMIT = 1000

def parse_pagination_args(*, default_limit: int = DEFAULT_LIMIT, max_limit: int = MAX_LIMIT):
    """
    Parse ?limit&offset. Returns (limit, offset, err)
    err is either None or (message, http_status).
    """
    try:
        limit  = int(request.args.get("limit", default_limit))
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        return None, None, ("limit/offset must be integers", 400)

    if limit < 1 or limit > max_limit or offset < 0:
        return None, None, (f"limit 1..{max_limit}, offset >= 0", 400)

    return limit, offset, None


def paginate(total: int | None, limit: int, offset: int, *, returned_count: int | None = None):
    """
    Compute the 'page' dict and whether a 'next' page likely exists.
    - If total is known: has_next = (offset + limit < total)
    - If total is unknown: has_next = (returned_count == limit) if provided, else False
    """
    page = {
        "total": int(total) if total is not None else None,
        "limit": limit,
        "offset": offset,
    }

    if isinstance(total, int):
        has_next = (offset + limit) < total
    else:
        has_next = bool(returned_count is not None and returned_count >= limit)

    return page, has_next


def _build_url_with_params(base_url: str, **updates) -> str:
    """
    Merge/replace query params without dropping existing ones.
    """
    parsed = urlparse(base_url)
    qs = parse_qs(parsed.query)
    for k, v in updates.items():
        qs[k] = [str(v)]
    new_qs = urlencode(qs, doseq=True)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", new_qs, ""))


def set_next_link(resp, base_url: str, limit: int, offset_next: int):
    parsed = urlparse(base_url)
    qs = parse_qs(parsed.query)

    # If base_url had no query (e.g., request.base_url), preserve current request args
    if not qs:
        # request.args is ImmutableMultiDict[str, str]; convert to lists for urlencode(doseq=True)
        qs = {k: [v] for k, v in request.args.items()}

    qs["limit"]  = [str(limit)]
    qs["offset"] = [str(offset_next)]

    next_url = urlunparse(parsed._replace(query=urlencode(qs, doseq=True)))
    val = f'<{next_url}>; rel="next"'
    existing = resp.headers.get("Link")
    resp.headers["Link"] = f"{existing}, {val}" if existing else val
    return resp


def append_prev_link_if_any(resp, base_url: str, limit: int, offset: int):
    """
    Optional helper: add rel="prev" when offset > 0.
    """
    if offset > 0:
        prev_off = max(0, offset - limit)
        prev_url = _build_url_with_params(base_url, limit=limit, offset=prev_off)
        val = f'<{prev_url}>; rel="prev"'
        existing = resp.headers.get("Link")
        resp.headers["Link"] = f"{existing}, {val}" if existing else val
    return resp

