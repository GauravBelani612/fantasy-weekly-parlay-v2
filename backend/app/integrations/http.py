"""Shared httpx client with a small retry policy.

Both upstreams are free, unauthenticated and occasionally flaky, so every call goes through
one place that reuses connections and backs off on 429/5xx.
"""

import asyncio
import logging
from typing import Any

import httpx

from app.config import settings

log = logging.getLogger(__name__)

_client: httpx.AsyncClient | None = None
_RETRY_STATUSES = {429, 500, 502, 503, 504}
_MAX_ATTEMPTS = 3


def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=settings.http_timeout_seconds,
            headers={"User-Agent": "fantasy-weekly-parlay/0.1"},
            follow_redirects=True,
        )
    return _client


async def close_client() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


class UpstreamError(RuntimeError):
    """A non-retryable or exhausted upstream failure."""


async def get_json(url: str, params: dict[str, Any] | None = None) -> Any:
    client = get_client()
    last_exc: Exception | None = None

    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            response = await client.get(url, params=params)
        except httpx.HTTPError as exc:
            last_exc = exc
        else:
            if response.status_code == 404:
                return None
            if response.status_code not in _RETRY_STATUSES:
                response.raise_for_status()
                if not response.content:
                    return None
                return response.json()
            last_exc = UpstreamError(f"{response.status_code} from {url}")

        if attempt < _MAX_ATTEMPTS:
            backoff = 0.5 * 2 ** (attempt - 1)
            log.warning("Retrying %s in %.1fs (attempt %d): %s", url, backoff, attempt, last_exc)
            await asyncio.sleep(backoff)

    raise UpstreamError(f"Failed to fetch {url}: {last_exc}")
