"""
Compatibility module to provide `HDT_MCP.hdt_api:app` when tests try a
relative import fallback. It re-exports the Flask app from the canonical
implementation in `HDT_CORE_INFRASTRUCTURE.HDT_API`.
"""

from HDT_CORE_INFRASTRUCTURE.HDT_API import app  # noqa: F401

__all__ = ["app"]
