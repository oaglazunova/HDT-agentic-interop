from __future__ import annotations

import uuid
from contextvars import ContextVar

_request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)


def new_request_id() -> str:
    return uuid.uuid4().hex


def get_request_id() -> str:
    rid = _request_id_ctx.get()
    if not rid:
        rid = new_request_id()
        _request_id_ctx.set(rid)
    return rid


def set_request_id(rid: str | None) -> None:
    if rid:
        _request_id_ctx.set(rid)
