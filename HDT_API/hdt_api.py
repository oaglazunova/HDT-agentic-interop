"""
Compatibility module to provide `HDT_API.hdt_api:app` expected by tests.

It re-exports the Flask `app` from the real implementation in
`HDT_CORE_INFRASTRUCTURE.HDT_API`.
"""

from HDT_CORE_INFRASTRUCTURE.HDT_API import app  # noqa: F401

__all__ = ["app"]