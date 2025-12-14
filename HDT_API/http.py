from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Optional

from flask import jsonify, make_response, request


def _stable_json_dumps(obj: Any) -> str:
    """Compact + deterministic JSON (no spaces, sorted keys)."""
    return json.dumps(obj, separators=(",", ":"), sort_keys=True, ensure_ascii=False)


def compute_etag(payload: Any, *, variant: Optional[Mapping[str, Any]] = None) -> str:
    """Compute a *strong* ETag based on the response body and a variant dict.

    Variant makes the ETag safe across different clients/queries.
    """
    h = hashlib.sha256()

    # Body
    h.update(_stable_json_dumps(payload).encode("utf-8"))

    # Variant (path, query, client id, plus caller-provided variant)
    cid = (getattr(request, "client", {}) or {}).get("client_id", "unknown")
    var: dict[str, Any] = {
        "path": request.path,
        "qs": request.query_string.decode("utf-8", "ignore"),
        "client_id": cid,
    }
    if variant:
        var.update(dict(variant))
    h.update(_stable_json_dumps(var).encode("utf-8"))

    # Strong ETag (quoted per RFC 7232)
    return f"\"{h.hexdigest()[:16]}\""


def json_with_headers(
    payload: Any,
    *,
    policy: Optional[str] = None,
    redactions: Optional[int] = None,
    status: int = 200,
    etag_variant: Optional[Mapping[str, Any]] = None,
    extra_headers: Optional[Mapping[str, str]] = None,
):
    """Return JSON with governance headers, plus conditional ETag/304.

    - Computes a stable ETag for 200 OK responses (optionally varied by 'etag_variant').
    - If If-None-Match matches, returns 304 with no body (still sets headers).
    - 'extra_headers' supports Link / X-Limit / X-Offset / X-Total, etc.
    """
    cid = (getattr(request, "client", {}) or {}).get("client_id", "unknown")
    users_count = len(payload) if isinstance(payload, list) else 1
    req_id = getattr(request, "request_id", None)

    extra = dict(extra_headers or {})

    # Compute ETag only for cacheable 200 responses
    etag: Optional[str] = None
    if status == 200:
        etag = compute_etag(payload, variant=etag_variant)

        # Conditional GET handling
        inm = request.headers.get("If-None-Match")
        if inm:
            candidates = [x.strip() for x in inm.split(",")]
            if etag in candidates:
                resp = make_response("", 304)
                resp.headers["ETag"] = etag
                resp.headers["X-Client-Id"] = str(cid)
                resp.headers["X-Users-Count"] = str(users_count)
                if policy is not None:
                    resp.headers["X-Policy"] = policy
                resp.headers["X-Request-Id"] = req_id or ""

                resp.headers["Access-Control-Allow-Origin"] = request.headers.get("Origin", "*")
                resp.headers["Vary"] = "Origin"
                resp.headers["Access-Control-Expose-Headers"] = (
                    "ETag, X-Client-Id, X-Users-Count, X-Policy, X-Request-Id, "
                    "Link, X-Limit, X-Offset, X-Total"
                )

                for k, v in extra.items():
                    resp.headers[k] = v
                resp.headers.setdefault("Cache-Control", "private, must-revalidate")
                return resp

    resp = jsonify(payload)
    resp.status_code = status
    resp.headers["X-Client-Id"] = str(cid)
    resp.headers["X-Users-Count"] = str(users_count)
    if policy is not None:
        resp.headers["X-Policy"] = policy
    if redactions is not None:
        resp.headers["X-Policy-Redactions"] = str(int(redactions))
    if etag is not None:
        resp.headers["ETag"] = etag
    if req_id is not None:
        resp.headers["X-Request-Id"] = req_id

    resp.headers["Access-Control-Allow-Origin"] = request.headers.get("Origin", "*")
    resp.headers["Vary"] = "Origin"
    resp.headers["Access-Control-Expose-Headers"] = (
        "ETag, X-Client-Id, X-Users-Count, X-Policy, X-Request-Id, Link, X-Limit, X-Offset, X-Total"
    )

    for k, v in extra.items():
        resp.headers[k] = v

    if status == 200:
        resp.headers.setdefault("Cache-Control", "private, must-revalidate")

    return resp


def api_error(
    code: str,
    message: str,
    *,
    status: int = 400,
    details: Optional[Mapping[str, Any]] = None,
    policy: str = "error",
):
    """Return a consistent error envelope via json_with_headers()."""
    payload: dict[str, Any] = {"error": {"code": code, "message": message}}
    if details:
        payload["error"]["details"] = dict(details)
    return json_with_headers(payload, status=status, policy=policy)
