from __future__ import annotations

from typing import Callable
import time as _time
import copy as _copy
import requests
import threading


def api_url(base_url: str, path: str) -> str:
    """Robustly join base and path to avoid duplicate/missing slashes."""
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def hdt_get(
    base_url: str,
    path: str,
    params: dict | None,
    headers_provider: Callable[[], dict],
    retry_max: int,
    get_request_id: Callable[[], str],
    set_request_id: Callable[[str | None], None],
) -> dict:
    """HTTP GET JSON with basic retry and request-id propagation.

    - Uses `headers_provider()` to supply auth/base headers.
    - Ensures a stable X-Request-Id across retries and updates it from server responses when present.
    """
    url = api_url(base_url, path)
    last: Exception | None = None
    rid = get_request_id()  # stable across retries
    for attempt in range(1, retry_max + 2):
        try:
            hdrs = dict(headers_provider())
            hdrs["X-Request-Id"] = rid
            r = requests.get(url, headers=hdrs, params=params or {}, timeout=30)
            r.raise_for_status()
            server_rid = r.headers.get("X-Request-Id")
            if server_rid:
                set_request_id(server_rid)
                rid = server_rid
            return r.json()
        except Exception as e:  # pragma: no cover - exercised in integration
            last = e
            if attempt <= retry_max:
                _time.sleep(0.5 * attempt)
            else:
                raise last


def cached_get(
    cache: dict,
    cache_lock: threading.Lock,
    cache_ttl: int,
    base_url: str,
    path: str,
    params: dict | None,
    headers_provider: Callable[[], dict],
    retry_max: int,
    get_request_id: Callable[[], str],
    set_request_id: Callable[[str | None], None],
) -> dict:
    """Cached GET with deep-copy safety to avoid in-place mutations leaking.

    Caches by (path, sorted(params.items())). Stores and returns deep copies so
    callers can freely mutate the payload (e.g., policy redaction) without
    corrupting the cache.
    """
    key = (path, tuple(sorted((params or {}).items())))
    now = _time.time()
    with cache_lock:
        hit = cache.get(key)
        if hit and now - hit[0] < cache_ttl:
            return _copy.deepcopy(hit[1])

    data = hdt_get(base_url, path, params, headers_provider, retry_max, get_request_id, set_request_id)
    with cache_lock:
        cache[key] = (now, _copy.deepcopy(data))
    return _copy.deepcopy(data)
