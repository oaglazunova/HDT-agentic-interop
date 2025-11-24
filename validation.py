"""
Compatibility shim so tests can import `validation` from the project root.

This re-exports the public API from `HDT_CORE_INFRASTRUCTURE.validation`.
"""

from HDT_CORE_INFRASTRUCTURE.validation import (
    sanitize_walk_record,
    sanitize_walk_records,
    ValidationError,
)

__all__ = [
    "sanitize_walk_record",
    "sanitize_walk_records",
    "ValidationError",
]
