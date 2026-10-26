"""Periodic RQ-scheduler job: enqueue a monitor_poll job for each due monitor.

Registered in apps/worker/.../entrypoint.py::_SCHEDULE. Reads the global poll
interval from SystemConfig.monitor_interval_seconds.
"""
from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from setvault_core.config import redis_url
from setvault_core.db import init_engine, run_job, session_factory
from setvault_core.services.monitors import due_monitors
from setvault_core.services.system_config import get_config

DATABASE_URL_ENV = "DATABASE_URL"


# A poll that's still waiting (the single worker may be busy with a long
# rip) hasn't updated last_checked_at yet, so the next dispatch tick would see
# the monitor as due again and stack another poll behind it.
_IN_FLIGHT = {"queued", "started", "deferred", "scheduled"}


def _poll_job_id(monitor_id: uuid.UUID) -> str:
    return f"monitor-poll-{monitor_id}"


def _enqueue_poll(monitor_id: uuid.UUID) -> bool:
    """Enqueue a poll unless one for this monitor is already in flight.
    Returns whether a job was enqueued."""
    from redis import Redis
    from rq import Queue
    from rq.job import Job

    redis = Redis.from_url(redis_url())
    job_id = _poll_job_id(monitor_id)
    existing = Job.fetch_many([job_id], connection=redis)[0]
    if existing is not None and existing.get_status(refresh=True) in _IN_FLIGHT:
        return False
    Queue("default", connection=redis).enqueue(
        "setvault_core.jobs.monitor_poll.run_poll_monitor", monitor_id=str(monitor_id),
        job_id=job_id,
    )
    return True


async def dispatch_monitors(
    session: AsyncSession, *, interval_seconds: int, now: datetime,
) -> int:
    """Enqueue a poll for each due monitor; returns how many were enqueued."""
    due = await due_monitors(session, interval_seconds=interval_seconds, now=now)
    return sum(1 for m in due if _enqueue_poll(m.id) is not False)


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
