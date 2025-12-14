"""Backward-compatible re-exports.

Prefer: hdt_api.services.pagination
"""

from .services.pagination import parse_pagination_args, paginate, set_next_link

__all__ = ["parse_pagination_args", "paginate", "set_next_link"]
