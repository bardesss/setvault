"""Shared enqueue for url-rip jobs.

Commit first, then enqueue: an idle worker can pick the job up within
milliseconds, and a RipJob row it cannot see yet is dropped as "not found",
leaving the job stuck in "queued". If the enqueue fails (Redis down) the
RipJob is marked failed so it shows up in Downloads and can be retried.
"""
from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from setvault_core.config import redis_url
from setvault_core.jobs.url_rip_job import RIP_JOB_TIMEOUT
from setvault_core.models.url_rip import RipJob

logger = logging.getLogger(__name__)


def _queue(url: str | None = None):
    from redis import Redis
    from rq import Queue

    return Queue("default", connection=Redis.from_url(url or redis_url()))


async def enqueue_rip(
    session: AsyncSession, job: RipJob, *, redis_url: str | None = None,
) -> bool:
    """Commit, then enqueue ``run_rip_job``. False if the enqueue failed (the
    job is then marked failed and that is committed too)."""
    job_id = job.id
    await session.commit()
    try:
        _queue(redis_url).enqueue(
            "setvault_core.jobs.url_rip_job.run_rip_job",
            rip_job_id=str(job_id),
            job_timeout=RIP_JOB_TIMEOUT,
        )
    except Exception:
        # The raw exception (Redis URL, hostnames) only goes to server logs.
        logger.exception("rip job %s: enqueue failed", job_id)
        job.status = "failed"
        job.error_text = "failed to enqueue worker"
        await session.commit()
        return False
    return True
