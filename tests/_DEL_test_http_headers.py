import types
from flask import request
from HDT_CORE_INFRASTRUCTURE.HDT_API import app, json_with_headers

def _set_request_client(client_id: str = "TEST_CLIENT"):
    # Attach a minimal .client dict as your decorator would
    request.client = {"client_id": client_id}

def test_json_with_headers_list_sets_counts_and_client_and_policy_and_cors_origin():
    payload = [{"user_id": 1}, {"user_id": 2}]

    with app.test_request_context("/", headers={"Origin": "http://example.com"}):
        _set_request_client("MODEL_DEV_X")
        resp = json_with_headers(payload, policy="allow", status=200)

        # status code
        assert resp.status_code == 200

        # governance headers
        assert resp.headers["X-Client-Id"] == "MODEL_DEV_X"
        assert resp.headers["X-Users-Count"] == "2"
        assert resp.headers["X-Policy"] == "allow"

        # CORS & exposure
        assert resp.headers["Access-Control-Allow-Origin"] == "http://example.com"
        assert resp.headers["Vary"] == "Origin"
        exposed = resp.headers["Access-Control-Expose-Headers"]
        for h in ("X-Client-Id", "X-Users-Count", "X-Policy"):
            assert h in exposed

def test_json_with_headers_single_sets_defaults_and_cors_wildcard_when_no_origin():
    payload = {"hello": "world"}

    with app.test_request_context("/"):
        _set_request_client("ANON_CLIENT")
        resp = json_with_headers(payload, policy=None, status=201)

        # status and counts
        assert resp.status_code == 201
        assert resp.headers["X-Client-Id"] == "ANON_CLIENT"
        assert resp.headers["X-Users-Count"] == "1"

        # X-Policy should NOT be set when policy=None
        assert "X-Policy" not in resp.headers

        # No Origin header => wildcard CORS
        assert resp.headers["Access-Control-Allow-Origin"] == "*"
        assert resp.headers["Vary"] == "Origin"

        exposed = resp.headers["Access-Control-Expose-Headers"]
        for h in ("X-Client-Id", "X-Users-Count", "X-Policy"):
            assert h in exposed
