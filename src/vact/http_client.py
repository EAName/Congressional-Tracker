"""Shared httpx client factory with tenacity retry and browser-like User-Agent."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = structlog.get_logger(__name__)

USER_AGENT = (
    "va-congressional-tracker/0.2 "
    "(+https://github.com/Democrats-for-Virginia; "
    "democrats-va-tracker; respectful academic/civic ingest)"
)

DEFAULT_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


def create_client(**kwargs: Any) -> httpx.Client:
    """Return an httpx.Client with the project User-Agent and timeouts."""
    headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    extra_headers = kwargs.pop("headers", None) or {}
    headers.update(extra_headers)
    timeout = kwargs.pop("timeout", DEFAULT_TIMEOUT)
    return httpx.Client(headers=headers, timeout=timeout, follow_redirects=True, **kwargs)


def get_with_retry(
    client: httpx.Client,
    url: str,
    *,
    max_attempts: int = 5,
    retry_on: Callable[[httpx.Response], bool] | None = None,
    allow_statuses: set[int] | None = None,
) -> httpx.Response:
    """
    GET with exponential backoff (max 5 attempts).

    Retries on transport errors and 5xx / 429 by default. Status codes in
    `allow_statuses` (e.g. {404}) are returned without raising so callers can
    treat them as terminal non-retryable outcomes.
    """
    allowed = allow_statuses or set()

    @retry(
        reraise=True,
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=1, min=1, max=30),
        retry=retry_if_exception_type((httpx.TransportError, httpx.TimeoutException)),
    )
    def _get() -> httpx.Response:
        response = client.get(url)
        if response.status_code in allowed:
            return response
        if response.status_code in {429, 500, 502, 503, 504}:
            logger.warning(
                "http_retryable_status",
                url=url,
                status_code=response.status_code,
            )
            response.raise_for_status()
        if retry_on is not None and retry_on(response):
            response.raise_for_status()
        return response

    return _get()
