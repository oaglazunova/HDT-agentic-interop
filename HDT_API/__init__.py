"""HDT Flask API package.

Run locally from repo root:

    python -m hdt_api.app

"""

from .app import create_app

__all__ = ["create_app"]
