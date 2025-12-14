"""Backward-compatible re-exports.

Prefer: hdt_api.services.fetchers
"""

from .services.fetchers import FetcherResult, fetch_walk_batch

__all__ = ["FetcherResult", "fetch_walk_batch"]
