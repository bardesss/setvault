"""Periodic RQ-scheduler job: enqueue a monitor_poll job for each due monitor.

Registered in apps/worker/.../entrypoint.py::_SCHEDULE. Reads the global poll
interval from SystemConfig.monitor_interval_seconds.
"""
from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from setvault_core.db import init_engine, run_job, session_factory
from setvault_core.services.monitors import due_monitors
from setvault_core.services.system_config import get_config

DATABASE_URL_ENV = "DATABASE_URL"


def _enqueue_poll(monitor_id: uuid.UUID) -> None:
    from redis import Redis
    from rq import Queue

    redis = Redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
    Queue("default", connection=redis).enqueue(
        "setvault_core.jobs.monitor_poll.run_poll_monitor", monitor_id=str(monitor_id),
    )


async def dispatch_monitors(
    session: AsyncSession, *, interval_seconds: int, now: datetime,
) -> int:
    due = await due_monitors(session, interval_seconds=interval_seconds, now=now)
    for m in due:
        _enqueue_poll(m.id)
    return len(due)


async def _run() -> int:
    if DATABASE_URL_ENV in os.environ:
        init_engine(os.environ[DATABASE_URL_ENV])
    async with session_factory()() as s:
        config = await get_config(s)
        return await dispatch_monitors(
            s, interval_seconds=config.monitor_interval_seconds, now=datetime.now(UTC),
        )


def run_dispatch_monitors() -> int:
    """RQ entry point (scheduled)."""
    return run_job(_run())
