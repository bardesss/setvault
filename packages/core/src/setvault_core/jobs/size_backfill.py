"""One-off backfill of set file sizes (``audio_bytes``/``stream_bytes``).

Probe and transcode record the sizes of new files; sets ingested before
those columns existed have none. The worker queues this job at start
(:func:`enqueue_if_needed`) while any set still lacks a size. It stats the
files on disk and fills only sizes that are NULL; a file that is missing
leaves its size NULL (Home then counts it as 0). Safe to re-run.
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from pathlib import Path

from sqlalchemy import and_, exists, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_core.config import redis_url
from setvault_core.db import init_engine, run_job, session_factory
from setvault_core.models.catalog import LiveSet, MediaRoot

logger = logging.getLogger(__name__)

BATCH_SIZE = 200
SIZE_BACKFILL_QUEUE = "low"
SIZE_BACKFILL_TIMEOUT = "1h"
JOB_FUNC = "setvault_core.jobs.size_backfill.run_size_backfill"
# Fixed, so a backfill already queued or running is not queued again.
JOB_ID = "size-backfill"
_IN_FLIGHT = {"queued", "started", "deferred", "scheduled"}
REDIS_TIMEOUT_SECONDS = 5
# Each size column and the path column naming the file it measures.
_PATH_COLUMNS = {"audio_bytes": LiveSet.audio_path, "stream_bytes": LiveSet.streaming_path}


def _needs_size():
    """A set in the vault with a size still to record."""
    return and_(
        LiveSet.deleted_at.is_(None),
        or_(
            LiveSet.audio_bytes.is_(None),
            and_(LiveSet.streaming_path.is_not(None), LiveSet.stream_bytes.is_(None)),
        ),
    )


def _size(path: Path) -> int | None:
    try:
        return path.stat().st_size
    except OSError:
        return None


def _sizes(paths: list[Path]) -> list[int | None]:
    return [_size(p) for p in paths]


async def _run_size_backfill() -> dict:
    """Returns ``{"checked", "filled", "missing"}``: the sets looked at, the
    sizes recorded and the files not found (one set can add two of each)."""
    if "DATABASE_URL" in os.environ:
        init_engine(os.environ["DATABASE_URL"])

    checked = filled = missing = 0
    after: uuid.UUID | None = None
    while True:
        async with session_factory()() as s:
            q = (
                select(LiveSet.id, MediaRoot.id, MediaRoot.host_path, LiveSet.audio_path,
                       LiveSet.audio_bytes, LiveSet.streaming_path, LiveSet.stream_bytes)
                .join(MediaRoot, MediaRoot.id == LiveSet.media_root_id)
                .where(_needs_size())
                .order_by(LiveSet.id)
                .limit(BATCH_SIZE)
            )
            if after is not None:
                q = q.where(LiveSet.id > after)
            rows = (await s.execute(q)).all()
            await s.commit()  # no transaction held across the stat calls
            if not rows:
                break
            after = rows[-1][0]

            # (set id, root id, column, relative path, absolute path)
            wanted = [
                (sid, root_id, col, rel, Path(host) / rel)
                for sid, root_id, host, audio_rel, audio_bytes, stream_rel, stream_bytes in rows
                for col, rel, known in (
                    ("audio_bytes", audio_rel, audio_bytes),
                    ("stream_bytes", stream_rel, stream_bytes),
                )
                if rel is not None and known is None
            ]
            sizes = await asyncio.to_thread(_sizes, [w[4] for w in wanted])

            checked += len(rows)
            for (sid, root_id, col, rel, _path), size in zip(wanted, sizes, strict=True):
                if size is None:
                    missing += 1
                    continue
                # Only while the row still names the measured file and has no
                # size. A transcode meanwhile records its own size; after a
                # rename or upgrade swap the set is left for the next run.
                res = await s.execute(
                    update(LiveSet)
                    .where(LiveSet.id == sid, LiveSet.media_root_id == root_id,
                           _PATH_COLUMNS[col] == rel, getattr(LiveSet, col).is_(None))
                    .values({col: size})
                )
                filled += res.rowcount or 0
            await s.commit()

    result = {"checked": checked, "filled": filled, "missing": missing}
    logger.info("size backfill: %s", result)
    return result


def run_size_backfill() -> dict:
    """RQ entrypoint."""
    return run_job(_run_size_backfill())


def _redis():
    from redis import Redis

    # Bounded, so a caller at worker start can't hang on an unreachable Redis.
    return Redis.from_url(
        redis_url(),
        socket_connect_timeout=REDIS_TIMEOUT_SECONDS, socket_timeout=REDIS_TIMEOUT_SECONDS,
    )


def _enqueue(redis=None) -> bool:
    """Queue the backfill under a fixed job id; skipped (False) while that job
    is still queued or running, so worker restarts don't stack runs."""
    from rq import Queue
    from rq.job import Job

    redis = redis if redis is not None else _redis()
    existing = Job.fetch_many([JOB_ID], connection=redis)[0]
    if existing is not None and existing.get_status(refresh=True) in _IN_FLIGHT:
        return False
    Queue(SIZE_BACKFILL_QUEUE, connection=redis).enqueue(
        JOB_FUNC, job_id=JOB_ID, job_timeout=SIZE_BACKFILL_TIMEOUT,
    )
    return True


async def enqueue_if_needed(session: AsyncSession, redis=None) -> bool:
    """Queue :func:`run_size_backfill` when a set in the vault still lacks a
    size and no backfill is queued or running yet; returns whether it was
    queued. ``redis``: a connection to reuse (default: a new one from
    ``REDIS_URL``, with connect/read timeouts)."""
    needed = (await session.execute(select(exists().where(_needs_size())))).scalar_one()
    if not needed:
        return False
    return _enqueue(redis)
