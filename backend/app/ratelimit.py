"""Tiny in-process sliding-window rate limiter.

Good enough for a single-instance deployment. If this ever runs on more than one worker,
swap the dict for Redis -- the call sites do not change.
"""

import time
from collections import defaultdict, deque

from fastapi import HTTPException, status

_hits: dict[str, deque[float]] = defaultdict(deque)


def enforce(key: str, limit: int, window_seconds: float, message: str) -> None:
    now = time.monotonic()
    bucket = _hits[key]
    cutoff = now - window_seconds
    while bucket and bucket[0] < cutoff:
        bucket.popleft()
    if len(bucket) >= limit:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, message)
    bucket.append(now)


def reset() -> None:
    _hits.clear()
