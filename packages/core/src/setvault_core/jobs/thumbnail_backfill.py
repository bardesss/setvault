"""Backfill of set covers for rips made before covers were stored.

Every rip's probe kept the platform's thumbnail URL in
``RipJob.probed_metadata``; only rips since :mod:`setvault_core.jobs.thumbnail`
also downloaded it. The worker queues this job at start
(:func:`enqueue_if_needed`) while a set without a cover still has such a URL.
A URL that no longer serves an image just leaves the set without one; the
next worker start tries it again. Safe to re-run.
"""
from __future__ import annotations

import logging
import os
import uuid

from sqlalchemy import and_, exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_core.db import init_engine, run_job, session_factory
from setvault_core.jobs.size_backfill import _IN_FLIGHT, _redis
from setvault_core.jobs.thumbnail import store_thumbnail
from setvault_core.models.catalog import LiveSet
from setvault_core.models.url_rip import RipJob

logger = logging.getLogger(__name__)

BATCH_SIZE = 100
THUMBNAIL_BACKFILL_QUEUE = "low"
THUMBNAIL_BACKFILL_TIMEOUT = "1h"
JOB_FUNC = "setvault_core.jobs.thumbnail_backfill.run_thumbnail_backfill"
# Fixed, so a backfill already queued or running is not queued again.
JOB_ID = "thumbnail-backfill"


def _probed_thumbnail():
    return RipJob.probed_metadata["thumbnail"].astext


def _needs_thumb():
    """A set in the vault without a cover whose rip recorded one."""
    return and_(
        LiveSet.deleted_at.is_(None),
        LiveSet.thumb_path.is_(None),
        RipJob.live_set_id == LiveSet.id,
        _probed_thumbnail().is_not(None),
        _probed_thumbnail() != "",
    )


async def _run_thumbnail_backfill() -> dict:
    """Returns ``{"checked", "stored"}``: the sets tried and the covers stored."""
    if "DATABASE_URL" in os.environ:
        init_engine(os.environ["DATABASE_URL"])

    checked = stored = 0
    after: uuid.UUID | None = None
    while True:
        async with session_factory()() as s:
            q = (
                select(LiveSet.id, _probed_thumbnail())
                .join(RipJob, RipJob.live_set_id == LiveSet.id)
                .where(_needs_thumb())
                .order_by(LiveSet.id, RipJob.created_at.desc())
                .limit(BATCH_SIZE)
            )
            if after is not None:
                q = q.where(LiveSet.id > after)
            rows = (await s.execute(q)).all()
        if not rows:
            break
        after = rows[-1][0]
        # A set ripped more than once (upgrades) has several jobs; the
        # newest one's thumbnail comes first.
        urls: dict[uuid.UUID, str] = {}
        for sid, url in rows:
            urls.setdefault(sid, url)
        for sid, url in urls.items():
            checked += 1
            if await store_thumbnail(str(sid), url):
                stored += 1

    result = {"checked": checked, "stored": stored}
    logger.info("thumbnail backfill: %s", result)
    return result


def run_thumbnail_backfill() -> dict:
    """RQ entrypoint."""
    return run_job(_run_thumbnail_backfill())


def _enqueue(redis=None) -> bool:
    """Queue the backfill under a fixed job id; skipped (False) while that job
    is still queued or running, so worker restarts don't stack runs."""
    from rq import Queue
    from rq.job import Job

    redis = redis if redis is not None else _redis()
    existing = Job.fetch_many([JOB_ID], connection=redis)[0]
    if existing is not None and existing.get_status(refresh=True) in _IN_FLIGHT:
        return False
    Queue(THUMBNAIL_BACKFILL_QUEUE, connection=redis).enqueue(
        JOB_FUNC, job_id=JOB_ID, job_timeout=THUMBNAIL_BACKFILL_TIMEOUT,
    )
    return True


async def enqueue_if_needed(session: AsyncSession, redis=None) -> bool:
    """Queue :func:`run_thumbnail_backfill` when a set still lacks a cover its
    rip recorded and no backfill is queued or running; returns whether it was
    queued."""
    needed = (await session.execute(select(exists().where(_needs_thumb())))).scalar_one()
    if not needed:
        return False
    return _enqueue(redis)
