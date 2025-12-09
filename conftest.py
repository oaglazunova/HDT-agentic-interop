"""Pytest configuration and shared fixtures."""
import sys
import os
import pytest

# Ensure project root on sys.path for absolute imports
ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

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

