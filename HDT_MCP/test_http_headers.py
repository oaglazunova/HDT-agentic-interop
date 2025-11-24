import uuid
import pytest

# Import the Flask app
try:
    from HDT_API.hdt_api import app
except Exception:
    # Fallback if tests are run from inside the package
    from .hdt_api import app  # type: ignore


@pytest.fixture(scope="module")
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_request_id_generated_when_absent(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    # Server should always echo a request id (generated if not provided)
    assert "X-Request-Id" in r.headers
    assert (r.headers["X-Request-Id"] or "").strip() != ""


def test_request_id_echoed_when_present(client):
    rid = uuid.uuid4().hex
    r = client.get("/healthz", headers={"X-Request-Id": rid})
    assert r.status_code == 200
    assert r.headers.get("X-Request-Id") == rid


def test_etag_and_304(client):
    # First call yields an ETag
    r1 = client.get("/healthz")
    assert r1.status_code == 200
    etag = r1.headers.get("ETag")
    assert etag and etag.strip() != ""

    # Second call with If-None-Match should return 304 and *no* body
    r2 = client.get("/healthz", headers={"If-None-Match": etag})
    assert r2.status_code == 304
    assert r2.data == b""
    # 304 should still echo governance headers
    assert "ETag" in r2.headers
    assert "X-Request-Id" in r2.headers
