import json
import pytest

try:
    from HDT_API.hdt_api import app
except Exception:
    from .hdt_api import app  # type: ignore


@pytest.fixture(scope="module")
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_openapi_served_and_contains_headers(client):
    r = client.get("/openapi.json")
    assert r.status_code == 200

    spec = r.get_json()
    assert spec["openapi"].startswith("3.")
    # Sanity checks for components you expose (correlation + paging)
    headers = spec["components"]["headers"]
    assert "X-Request-Id" in headers
    assert "ETag" in headers
    assert "X-Limit" in headers and "X-Offset" in headers

    # Path sanity: /get_walk_data documented with 200 + 304
    assert "/get_walk_data" in spec["paths"]
    responses = spec["paths"]["/get_walk_data"]["get"]["responses"]
    assert "200" in responses and "304" in responses
