"""Pytest configuration and shared fixtures."""
import sys
import os
import pathlib
import tempfile
import json
import pytest

# Ensure project root on sys.path for absolute imports
ROOT = pathlib.Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Prefer config-driven toggle for in-process Flask during tests.
# If the caller hasn't set HDT_SETTINGS_PATH or HDT_API_INPROC explicitly,
# create a temporary settings JSON that enables in-proc for the test run only.
if ("HDT_SETTINGS_PATH" not in os.environ) and ("HDT_API_INPROC" not in os.environ):
    try:
        tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
        json.dump({"hdt_api_inproc": True}, tmp)
        tmp.flush(); tmp.close()
        os.environ["HDT_SETTINGS_PATH"] = tmp.name
    except Exception:
        # Fallback to env if temp file fails for any reason
        os.environ["HDT_API_INPROC"] = "1"

# Expose a Flask app and client fixtures used across tests
try:
    from HDT_CORE_INFRASTRUCTURE.HDT_API import app as _flask_app
except Exception:  # pragma: no cover - fallback via shim
    from HDT_API.hdt_api import app as _flask_app  # type: ignore


@pytest.fixture(scope="session")
def app():
    """Return the Flask app configured for testing."""
    _flask_app.config.setdefault("TESTING", True)
    return _flask_app


@pytest.fixture()
def app_client(app):
    """A Flask test client for the app."""
    with app.test_client() as c:
        yield c


@pytest.fixture()
def client(app_client):
    """Alias used by some tests."""
    yield app_client

