"""Admin-triggered backfill: give existing sets a raw chromaprint fingerprint
and a measured audio quality.

The fill phase only fills data; it never touches ``duplicate_of``,
``status`` or deleted state. Safe to re-run: only sets that still lack a
current-version fingerprint or a quality measurement are picked up, oldest
first. With ``cleanup=True`` a second phase then merges published sets that
turn out to be the same audio (``services/set_merge``, spec §4.7) and the
admins get one summary notification at the end.

Gentle on the single worker: each RQ job runs one bounded slice (time and
set count), then re-enqueues itself at the back of the queue so uploads
queued meanwhile run in between. A set that fails is marked
(``quality_backfill_failed_at``) and not retried. The cleanup phase is
sliced the same way and carries its position (a cursor over the sets, oldest
first) and the running counts from slice to slice in the job's kwargs.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_core.db import init_engine, run_job, session_factory
from setvault_core.jobs.fingerprint import store_fingerprint
from setvault_core.models.catalog import LiveSet, MediaRoot, SetFingerprint
from setvault_core.services.audio_match import (
    MATCHER_VERSION,
    compute_legacy_digest,
    compute_raw_fingerprint,
    raw_to_bytes,
)
from setvault_core.services.audio_quality import apply_quality, measure_quality
from setvault_core.services.notifications import notify_backfill_summary
from setvault_core.services.set_merge import run_cleanup_batch, scan_duplicate_pairs

logger = logging.getLogger(__name__)

# One slice is BATCH_SECONDS plus at most one set in flight (two fpcalc runs
# of up to 900 s each and the 180 s quality check), which fits in this.
QUALITY_BACKFILL_TIMEOUT = "1h"
BATCH_SECONDS = 300
BATCH_MAX_SETS = 50
# Time budget for counting duplicate pairs in the admin dry run (a request).
DRY_RUN_SECONDS = 20
JOB_FUNC = "setvault_core.jobs.quality_backfill.run_quality_backfill"


def _has_current_fingerprint():
    return (
        select(SetFingerprint.id)
        .where(
            SetFingerprint.live_set_id == LiveSet.id,
            SetFingerprint.raw.is_not(None),
            SetFingerprint.raw_version >= MATCHER_VERSION,
        )
        .exists()
    )


def _not_failed():
    return LiveSet.quality_backfill_failed_at.is_(None)


async def backfill_candidates(session: AsyncSession) -> dict:
    to_fingerprint = (await session.execute(
        select(func.count()).select_from(LiveSet)
        .where(~_has_current_fingerprint(), _not_failed())
    )).scalar_one()
    to_measure = (await session.execute(
        select(func.count()).select_from(LiveSet)
        .where(LiveSet.quality_measured_at.is_(None), _not_failed())
    )).scalar_one()
    return {"to_fingerprint": int(to_fingerprint), "to_measure": int(to_measure)}


async def duplicate_pair_counts(session: AsyncSession) -> dict:
    """Dry run for the cleanup: same-audio pairs among published sets that
    already have a fingerprint (sets the backfill still has to fingerprint
    can't be counted yet). The scan compares fingerprints, so it is cut off
    after DRY_RUN_SECONDS; ``duplicate_pairs_complete`` says whether it
    finished. Changes nothing."""
    pairs, complete = await scan_duplicate_pairs(
        session, deadline=time.monotonic() + DRY_RUN_SECONDS,
    )
    return {"duplicate_pairs": len(pairs), "duplicate_pairs_complete": complete}


async def run_backfill_batch(
    limit: int | None = None, deadline: float | None = None,
) -> dict:
    """Process up to ``limit`` (default BATCH_MAX_SETS) sets, oldest first.

    Returns ``{"processed", "remaining", "errors", "error_ids",
    "fingerprinted", "measured"}``. A set that
    fails gets ``quality_backfill_failed_at`` and drops out of the candidates
    and of ``remaining``, so a permanently broken file cannot stall the
    backfill. ``deadline`` (``time.monotonic()`` value) is checked before each
    set; once passed the batch stops and the unprocessed sets stay in
    ``remaining``.
    """
    if "DATABASE_URL" in os.environ:
        init_engine(os.environ["DATABASE_URL"])

    pending = and_(
        or_(~_has_current_fingerprint(), LiveSet.quality_measured_at.is_(None)),
        _not_failed(),
    )
    async with session_factory()() as s:
        ids = list((await s.execute(
            select(LiveSet.id).where(pending)
            .order_by(LiveSet.created_at, LiveSet.id)
            .limit(BATCH_MAX_SETS if limit is None else limit)
        )).scalars())

    processed = fingerprinted = measured = 0
    error_ids: list[uuid.UUID] = []
    for live_set_id in ids:
        if deadline is not None and time.monotonic() >= deadline:
            break
        try:
            did_fp, did_quality = await _backfill_one(live_set_id)
        except Exception:
            logger.warning("quality backfill failed for %s", live_set_id, exc_info=True)
            error_ids.append(live_set_id)
            await _mark_failed(live_set_id)
        else:
            processed += 1
            fingerprinted += did_fp
            measured += did_quality

    async with session_factory()() as s:
        remaining = (await s.execute(
            select(func.count()).select_from(LiveSet).where(pending)
        )).scalar_one()
    return {
        "processed": processed, "remaining": int(remaining),
        "errors": len(error_ids), "error_ids": error_ids,
        "fingerprinted": fingerprinted, "measured": measured,
    }


async def _mark_failed(live_set_id: uuid.UUID) -> None:
    async with session_factory()() as s:
        live = await s.get(LiveSet, live_set_id)
        if live is not None:
            live.quality_backfill_failed_at = datetime.now(UTC)
            await s.commit()


async def _backfill_one(live_set_id: uuid.UUID) -> tuple[bool, bool]:
    """Returns (fingerprinted, measured)."""
    # Short sessions only: no DB connection is held across the slow
    # fpcalc/ffprobe thread calls.
    async with session_factory()() as s:
        live = await s.get(LiveSet, live_set_id)
        if live is None:
            raise RuntimeError(f"LiveSet {live_set_id} missing")
        root = await s.get(MediaRoot, live.media_root_id)
        if root is None:
            raise RuntimeError("MediaRoot vanished")
        path = Path(root.host_path) / live.audio_path
        need_quality = live.quality_measured_at is None
        need_fp = (await s.execute(
            select(SetFingerprint.id).where(
                SetFingerprint.live_set_id == live.id,
                SetFingerprint.raw.is_not(None),
                SetFingerprint.raw_version >= MATCHER_VERSION,
            ).limit(1)
        )).first() is None
    if not path.is_file():
        raise FileNotFoundError(str(path))

    if need_fp:
        raw, duration = await asyncio.to_thread(compute_raw_fingerprint, path)
        raw_bytes = raw_to_bytes(raw)
        digest = await asyncio.to_thread(compute_legacy_digest, path)
        async with session_factory()() as s:
            await store_fingerprint(s, live_set_id, raw_bytes, digest, duration)
            await s.commit()

    if need_quality:
        quality = await asyncio.to_thread(measure_quality, path)
        async with session_factory()() as s:
            live = await s.get(LiveSet, live_set_id)
            if live is not None:
                apply_quality(live, quality)
                await s.commit()
    return need_fp, need_quality


_COUNT_KEYS = ("fingerprinted", "measured", "merged", "skipped", "errors")


def enqueue_quality_backfill(**state):
    """Put one backfill slice at the back of the default queue. ``state``
    (cleanup runs only) is passed on to :func:`run_quality_backfill`."""
    from redis import Redis
    from rq import Queue

    redis = Redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
    queue = Queue("default", connection=redis)
    if state:
        return queue.enqueue(JOB_FUNC, job_timeout=QUALITY_BACKFILL_TIMEOUT, kwargs=state)
    return queue.enqueue(JOB_FUNC, job_timeout=QUALITY_BACKFILL_TIMEOUT)


def start_quality_backfill(*, cleanup: bool = False):
    """Queue the first slice of a backfill run."""
    if cleanup:
        return enqueue_quality_backfill(
            cleanup=True, phase="fill", counts=dict.fromkeys(_COUNT_KEYS, 0), cursor=None,
        )
    return enqueue_quality_backfill()


async def _run_quality_backfill(
    *, cleanup: bool = False, phase: str = "fill",
    counts: dict | None = None, cursor: list | None = None,
) -> dict:
    """One slice: BATCH_SECONDS or BATCH_MAX_SETS, whichever comes first.

    Without ``cleanup`` only the fill phase runs. With it, the fill slices
    are followed by cleanup slices (``phase="cleanup"``); the last one sends
    the admin summary."""
    counts = {**dict.fromkeys(_COUNT_KEYS, 0), **(counts or {})}
    deadline = time.monotonic() + BATCH_SECONDS
    if phase == "cleanup":
        res = await run_cleanup_batch(cursor=cursor, deadline=deadline)
        counts["merged"] += res["merged"]
        counts["skipped"] += res["skipped"]
        counts["errors"] += res["errors"]  # cleanup pairs that failed
        if not res["done"]:
            enqueue_quality_backfill(
                cleanup=True, phase="cleanup", counts=counts, cursor=res["cursor"],
            )
            logger.info("duplicate cleanup: slice done %s, next slice queued", res)
            return res
        logger.info("duplicate cleanup: finished %s", counts)
        await _send_summary(counts)
        return res

    res = await run_backfill_batch(deadline=deadline)
    counts["fingerprinted"] += res["fingerprinted"]
    counts["measured"] += res["measured"]
    # Persisted failures mean every slice that did work shrinks `remaining`;
    # a slice that did nothing must not loop forever.
    if res["remaining"] > 0 and res["processed"] + res["errors"] > 0:
        if cleanup:
            enqueue_quality_backfill(cleanup=True, phase="fill", counts=counts, cursor=None)
        else:
            enqueue_quality_backfill()
        logger.info("quality backfill: slice done %s, next slice queued", res)
    elif cleanup:
        # Everything that can be fingerprinted is: look for duplicates next,
        # in its own slice so queued uploads run first.
        enqueue_quality_backfill(cleanup=True, phase="cleanup", counts=counts, cursor=None)
        logger.info("quality backfill: fill finished %s, cleanup queued", res)
    else:
        logger.info("quality backfill: finished %s", res)
    return res


async def _send_summary(counts: dict) -> None:
    try:
        async with session_factory()() as s:
            await notify_backfill_summary(s, counts)
            await s.commit()
    except Exception:
        # The cleanup itself is done; a missing bell entry must not fail it.
        logger.exception("backfill summary notification failed")


def run_quality_backfill(
    cleanup: bool = False, phase: str = "fill",
    counts: dict | None = None, cursor: list | None = None,
) -> dict:
    """RQ entrypoint."""
    return run_job(_run_quality_backfill(
        cleanup=cleanup, phase=phase, counts=counts, cursor=cursor,
    ))
