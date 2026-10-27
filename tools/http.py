"""Small resilient HTTP helper shared by the tools: timeouts + bounded retries."""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

RETRYABLE_STATUS = {429, 500, 502, 503, 504}
TIMEOUT_SECONDS = float(os.getenv("HTTP_TIMEOUT_SECONDS", "10"))
USER_AGENT = "se-interview-travel-agent/0.2"


class UpstreamError(RuntimeError):
    """Raised when an upstream API cannot be reached or keeps failing."""


def get_json(
    url: str,
    params: dict[str, Any] | None = None,
    *,
    retries: int = 2,
    backoff_seconds: float = 0.5,
) -> Any:
    """GET ``url`` and return the decoded JSON body.

    Transport errors and 429/5xx responses are retried with exponential backoff. Other 4xx
    responses are raised immediately as ``httpx.HTTPStatusError``: they are caller errors and
    retrying would not help.
    """
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with httpx.Client(timeout=TIMEOUT_SECONDS, headers={"User-Agent": USER_AGENT}) as client:
                response = client.get(url, params=params)
            if response.status_code in RETRYABLE_STATUS:
                raise httpx.HTTPStatusError(
                    f"retryable status {response.status_code}",
                    request=response.request,
                    response=response,
                )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code not in RETRYABLE_STATUS:
                raise
            last_exc = exc
        except httpx.TransportError as exc:
            last_exc = exc
        if attempt < retries:
            delay = backoff_seconds * (2**attempt)
            logger.warning("GET %s failed (%s); retrying in %.1fs", url, last_exc, delay)
            time.sleep(delay)
    raise UpstreamError(f"GET {url} failed after {retries + 1} attempts: {last_exc}") from last_exc
