"""Redis sliding-window rate limiter keyed by ingest-source kind.

Mirrors apps/web/.../rate_limit.py::hit but lives in core so both the web
process and the worker (monitor polls) share one budget per source. Exceeding
the limit is NOT a source health failure — callers skip the call and retry on
the next poll rather than incrementing the auto-disable counter.
"""
from __future__ import annotations

import asyncio
import logging
import time

from redis.asyncio import Redis

from setvault_core.config import redis_url

logger = logging.getLogger(__name__)

_redis: Redis | None = None
_redis_loop: asyncio.AbstractEventLoop | None = None


def _client() -> Redis:
    """Return a process-wide Redis client.

    redis.asyncio connections bind to the event loop that created them. The web
    and worker processes each run a single long-lived loop, so the client is
    created once. The test suite, however, spins up a fresh loop per test; reusing
    a client from a previous (now-closed) loop raises "Event loop is closed". To
    stay correct in both worlds we recreate the client whenever the running loop
    differs from the one the cached client was built on.
    """
    global _redis, _redis_loop
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if _redis is None or loop is not _redis_loop:
        url = redis_url()
        _redis = Redis.from_url(url, decode_responses=True)
        _redis_loop = loop
    return _redis


async def allow(kind: str, *, limit: int, window_seconds: int) -> bool:
    """Increment the per-kind counter for the current window bucket. Returns
    True if the call is within budget, False if it would exceed `limit`."""
    if limit <= 0:
        return True
    if window_seconds < 1:
        logger.warning(
            "source %s has non-positive rate-limit window %s; using 1s", kind, window_seconds
        )
        window_seconds = 1
    redis = _client()
    bucket = int(time.time() // window_seconds)
    key = f"srcrl:{kind}:{bucket}"
    pipe = redis.pipeline()
    pipe.incr(key, 1)
    pipe.expire(key, window_seconds + 1)
    count, _ = await pipe.execute()
    return int(count) <= limit
