"""
Lightweight shared HTTP client.

Goals:
- Centralize timeouts, retries, and error logging.
- Keep dependencies limited to `requests` (and its bundled urllib3).
- Provide a small, testable surface area for all upstream fetchers.

This module intentionally avoids any framework coupling (Flask/MCP/etc.).
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Mapping

import requests
from requests import Response
from requests.adapters import HTTPAdapter

try:
    # requests vendors urllib3; this import works in normal environments
    from urllib3.util.retry import Retry
except Exception:  # pragma: no cover
    Retry = None  # type: ignore


logger = logging.getLogger(__name__)


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except Exception:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default


# Reasonable defaults for upstream APIs (GameBus / Google Fit)
DEFAULT_CONNECT_TIMEOUT_S = _env_float("HDT_HTTP_CONNECT_TIMEOUT", 3.05)
DEFAULT_READ_TIMEOUT_S = _env_float("HDT_HTTP_READ_TIMEOUT", 20.0)
DEFAULT_TIMEOUT = (DEFAULT_CONNECT_TIMEOUT_S, DEFAULT_READ_TIMEOUT_S)

DEFAULT_RETRIES = _env_int("HDT_HTTP_RETRIES", 3)
DEFAULT_BACKOFF = _env_float("HDT_HTTP_BACKOFF", 0.4)

# Retries are only applied to idempotent methods by default.
DEFAULT_RETRY_STATUS = (429, 500, 502, 503, 504)


@dataclass(frozen=True)
class HttpClientConfig:
    timeout: tuple[float, float] = DEFAULT_TIMEOUT
    retries: int = DEFAULT_RETRIES
    backoff: float = DEFAULT_BACKOFF
    retry_statuses: tuple[int, ...] = DEFAULT_RETRY_STATUS
    user_agent: str = os.getenv("HDT_HTTP_USER_AGENT", "HDT-agentic-interop/1.0")


class HttpClient:
    """A small wrapper around `requests.Session` with sane defaults."""

    def __init__(self, *, config: HttpClientConfig | None = None, session: requests.Session | None = None) -> None:
        self.config = config or HttpClientConfig()
        self.session = session or requests.Session()
        self._configure_session(self.session, self.config)

    @staticmethod
    def _configure_session(session: requests.Session, config: HttpClientConfig) -> None:
        # Always set a UA; allow callers to override per-request.
        session.headers.setdefault("User-Agent", config.user_agent)

        # Configure retries (if urllib3 Retry is available).
        if Retry is None or config.retries <= 0:
            return

        # urllib3 Retry API differs slightly across versions; support both.
        try:
            retry = Retry(
                total=config.retries,
                connect=config.retries,
                read=config.retries,
                status=config.retries,
                backoff_factor=config.backoff,
                status_forcelist=config.retry_statuses,
                allowed_methods=frozenset(["HEAD", "GET", "OPTIONS"]),
                respect_retry_after_header=True,
                raise_on_status=False,
            )
        except TypeError:  # pragma: no cover
            retry = Retry(
                total=config.retries,
                connect=config.retries,
                read=config.retries,
                status=config.retries,
                backoff_factor=config.backoff,
                status_forcelist=config.retry_statuses,
                method_whitelist=frozenset(["HEAD", "GET", "OPTIONS"]),
                respect_retry_after_header=True,
                raise_on_status=False,
            )

        adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10)
        session.mount("https://", adapter)
        session.mount("http://", adapter)

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, Any] | None = None,
        json: Any | None = None,
        data: Any | None = None,
        timeout: tuple[float, float] | float | None = None,
        allow_redirects: bool = True,
        **kwargs: Any,
    ) -> Response:
        """Perform an HTTP request and raise for non-2xx responses."""
        t0 = time.perf_counter()
        try:
            resp = self.session.request(
                method=method,
                url=url,
                headers=dict(headers) if headers else None,
                params=dict(params) if params else None,
                json=json,
                data=data,
                timeout=timeout or self.config.timeout,
                allow_redirects=allow_redirects,
                **kwargs,
            )
            resp.raise_for_status()
            return resp
        except requests.RequestException as e:
            ms = int((time.perf_counter() - t0) * 1000)
            status = getattr(getattr(e, "response", None), "status_code", None)
            logger.warning(
                "HTTP %s %s failed (status=%s, ms=%s): %s",
                method.upper(),
                url,
                status,
                ms,
                str(e),
            )
            raise

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, Any] | None = None,
        timeout: tuple[float, float] | float | None = None,
        **kwargs: Any,
    ) -> Response:
        return self.request("GET", url, headers=headers, params=params, timeout=timeout, **kwargs)

    def get_json(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, Any] | None = None,
        timeout: tuple[float, float] | float | None = None,
        **kwargs: Any,
    ) -> Any:
        resp = self.get(url, headers=headers, params=params, timeout=timeout, **kwargs)
        return resp.json()


# A single shared client is sufficient for the current codebase.
DEFAULT_HTTP_CLIENT = HttpClient()
