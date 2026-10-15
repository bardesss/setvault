from __future__ import annotations

import asyncio
import os
from collections.abc import Coroutine
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

_engine: AsyncEngine | None = None
_factory: async_sessionmaker[AsyncSession] | None = None
# (url, nullpool, loop) the current engine was built for; lets init_engine()
# hand back the same engine when a job's stages re-init on the same loop.
_engine_key: tuple[str, bool, asyncio.AbstractEventLoop] | None = None


def _nullpool_enabled() -> bool:
    return os.environ.get("SETVAULT_DB_NULLPOOL", "").lower() in ("1", "true", "yes")


def _running_loop() -> asyncio.AbstractEventLoop | None:
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None


def init_engine(url: str) -> AsyncEngine:
    global _engine, _factory, _engine_key
    nullpool = _nullpool_enabled()
    loop = _running_loop()
    # Every pipeline stage calls init_engine() at its start. Building a fresh
    # pooled engine each time would strand the previous engine's idle
    # connections, so reuse the engine when nothing relevant changed. Engines
    # built outside a running loop (web startup) are never reused this way.
    if (_engine is not None and loop is not None
            and _engine_key == (url, nullpool, loop)):
        return _engine
    _engine_key = (url, nullpool, loop) if loop is not None else None
    if nullpool:
        # Test suites create many short-lived engines (the web conftest calls
        # init_engine in ~17 autouse fixtures per test). A real pool leaves idle
        # asyncpg connections lingering, exhausting Postgres's max_connections on
        # CI. NullPool opens/closes a connection per use and sidesteps asyncio
        # event-loop binding — the same strategy the core test fixtures use.
        _engine = create_async_engine(url, poolclass=NullPool, future=True)
    else:
        _engine = create_async_engine(url, pool_pre_ping=True, future=True)
    _factory = async_sessionmaker(_engine, expire_on_commit=False, class_=AsyncSession)
    return _engine


def engine() -> AsyncEngine:
    if _engine is None:
        raise RuntimeError("Engine not initialized — call init_engine() first")
    return _engine


def session_factory() -> async_sessionmaker[AsyncSession]:
    if _factory is None:
        raise RuntimeError("Engine not initialized — call init_engine() first")
    return _factory


def run_job[T](coro: Coroutine[Any, Any, T]) -> T:
    """``asyncio.run`` for sync RQ entrypoints.

    Disposes the current engine before the loop closes. A pooled asyncpg
    connection is bound to the loop that opened it, so connections left in the
    pool after ``asyncio.run`` returns can never be reused or cleanly closed.
    The engine itself stays usable: its next checkout opens a fresh pool.
    """
    async def _main() -> T:
        try:
            return await coro
        finally:
            if _engine is not None:
                await _engine.dispose()

    return asyncio.run(_main())
