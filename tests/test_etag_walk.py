# tests/test_etag_walk.py
import os
import json
import pytest

# Import the canonical Flask app directly from the implementation
from hdt_api.app import app


@pytest.fixture(scope="module")
def client():
    app.config.update(TESTING=True)
    with app.test_client() as c:
        yield c


def _auth_headers():
    # Your API accepts either header; send both for parity with README.
    api_key = os.getenv("MODEL_DEVELOPER_1_API_KEY") or "MODEL_DEVELOPER_1"
    return {
        "Authorization": f"Bearer {api_key}",
        "X-API-KEY": api_key,
    }


def test_etag_roundtrip_single_user_304(client):
    """
    1) GET -> 200, capture ETag
    2) GET with If-None-Match -> 304
       and ETag, X-Request-Id, X-Limit, X-Offset headers preserved
    3) Changing the query (offset) yields a different ETag
    """
    headers = _auth_headers()

    # Use a placeholder-connected user from sample config (e.g., user_id=2)
    # Include explicit paging so X-Limit/X-Offset are present.
    q = "/get_walk_data?user_id=2&limit=5&offset=0"

    # 1) Initial 200 with ETag
    r1 = client.get(q, headers=headers)
    assert r1.status_code == 200, r1.get_data(as_text=True)

    etag = r1.headers.get("ETag")
    assert etag, "ETag header missing on 200 response"

    # Sanity: payload is JSON (list of envelopes per API contract)
    # (Content may be empty/error per placeholder data, that's OK for ETag.)
    assert isinstance(r1.get_json(), list)

    # 2) Conditional GET with If-None-Match -> 304 + headers preserved
    r2 = client.get(q, headers={**headers, "If-None-Match": etag})
    assert r2.status_code == 304
    assert r2.headers.get("ETag") == etag
    assert r2.headers.get("X-Request-Id")  # must be present
    # Paging headers are kept even on 304 via json_with_headers(...)
    assert r2.headers.get("X-Limit") == "5"
    assert r2.headers.get("X-Offset") == "0"
    # Body should be empty for 304
    assert (r2.data or b"") in (b"",)  # Flask sets empty body

    # Optional: cache policy hint present on 304
    cache_ctrl = r2.headers.get("Cache-Control", "")
    assert "must-revalidate" in cache_ctrl

    # 3) Changing the query (here: offset) should produce a different ETag
    r3 = client.get("/get_walk_data?user_id=2&limit=5&offset=5", headers=headers)
    assert r3.status_code == 200
    etag_2 = r3.headers.get("ETag")
    assert etag_2 and etag_2 != etag, "ETag should vary with query (offset)"
