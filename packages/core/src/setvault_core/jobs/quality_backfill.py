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
(``quality_backfill_failed_at``) and not retried, unless its audio file
changes after the failure or an admin asks for a retry
(:func:`clear_backfill_failures`). Only one chain runs at a time
(:func:`quality_backfill_in_flight`). The cleanup phase is
sliced the same way and carries its position (a cursor over the sets, oldest
first) and the running counts from slice to slice in the job's kwargs.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_core.config import redis_url
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
JOB_FUNC = "setvault_core.jobs.quality_backfill.run_quality_backfill"
# The duplicate scan for the Quality tab runs in the worker (it compares
# fingerprints, CPU-bound): an admin "Refresh" queues it, and so does the end
# of a cleanup run. Its result is cached in Redis for the GET.
SCAN_FUNC = "setvault_core.jobs.quality_backfill.run_duplicate_scan"
# The scan stops after this long and reports itself incomplete; the job
# timeout leaves room for loading the fingerprint index on top.
DUPLICATE_SCAN_SECONDS = 10 * 60
DUPLICATE_SCAN_TIMEOUT = "30m"
SCAN_CACHE_KEY = "setvault:quality-backfill:duplicate-scan"
# Id of the latest queued scan, so repeated Refresh clicks don't stack scans.
SCAN_JOB_KEY = "setvault:quality-backfill:duplicate-scan-job"
# Short lock around "check in flight, then enqueue" (like START_LOCK_KEY).
SCAN_LOCK_KEY = "setvault:quality-backfill:duplicate-scan-lock"
SCAN_LOCK_SECONDS = 30
# Redis key holding the id of the chain's latest slice (singleton check).
CHAIN_KEY = "setvault:quality-backfill:chain"
# Short lock around "check in flight, then enqueue" so two concurrent starts
# can't both pass the check and run two chains.
START_LOCK_KEY = "setvault:quality-backfill:start-lock"
START_LOCK_SECONDS = 30
_IN_FLIGHT = {"queued", "started", "deferred", "scheduled"}


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
    failed = (await session.execute(
        select(func.count()).select_from(LiveSet)
        .where(LiveSet.quality_backfill_failed_at.is_not(None))
    )).scalar_one()
    return {
        "to_fingerprint": int(to_fingerprint), "to_measure": int(to_measure),
        "failed": int(failed),
    }


async def clear_backfill_failures(session: AsyncSession) -> int:
    """Admin retry: forget every failure marker so the next run tries those
    sets again. Returns how many were cleared; the caller commits."""
    res = await session.execute(
        update(LiveSet).where(LiveSet.quality_backfill_failed_at.is_not(None))
        .values(quality_backfill_failed_at=None)
    )
    return int(res.rowcount or 0)


def _changed_since(path: Path, when: datetime) -> bool:
    try:
        return path.stat().st_mtime > when.timestamp()
    except OSError:
        return False


async def clear_stale_failures(session: AsyncSession) -> int:
    """Clear the marker of each failed set whose audio file was modified
    after it failed (the file was fixed or replaced). Returns how many; the
    caller commits. Failed sets are few, so stat-ing each one is cheap."""
    rows = (await session.execute(
        select(LiveSet.id, MediaRoot.host_path, LiveSet.audio_path,
               LiveSet.quality_backfill_failed_at)
        .join(MediaRoot, MediaRoot.id == LiveSet.media_root_id)
        .where(LiveSet.quality_backfill_failed_at.is_not(None))
    )).all()
    if not rows:
        return 0
    changed = await asyncio.to_thread(lambda: [
        sid for sid, root, rel, failed_at in rows
        if _changed_since(Path(root) / rel, failed_at)
    ])
    if changed:
        await session.execute(
            update(LiveSet).where(LiveSet.id.in_(changed))
            .values(quality_backfill_failed_at=None)
        )
    return len(changed)


async def duplicate_pair_counts(session: AsyncSession) -> dict:
    """Same-audio pairs among published sets that already have a
    fingerprint (sets the backfill still has to fingerprint can't be counted
    yet). The scan compares fingerprints, so it is cut off after
    DUPLICATE_SCAN_SECONDS; ``duplicate_pairs_complete`` says whether it
    finished. Changes nothing. Worker only: CPU-bound."""
    pairs, complete = await scan_duplicate_pairs(
        session, deadline=time.monotonic() + DUPLICATE_SCAN_SECONDS,
    )
    return {"duplicate_pairs": len(pairs), "duplicate_pairs_complete": complete}


def cached_duplicate_scan() -> dict:
    """The last duplicate scan as cached by the worker:
    ``{"duplicate_pairs", "duplicate_pairs_complete", "scanned_at"}``, all
    None when no scan has run (or the cache is unreadable)."""
    empty = {"duplicate_pairs": None, "duplicate_pairs_complete": None, "scanned_at": None}
    try:
        raw = _redis().get(SCAN_CACHE_KEY)
        data = json.loads(raw) if raw else None
    except Exception:
        logger.warning("duplicate scan cache unreadable", exc_info=True)
        return empty
    if not isinstance(data, dict):
        return empty
    return {k: data.get(k) for k in empty}


async def refresh_duplicate_scan() -> dict:
    """Scan for duplicate pairs and cache the result (worker side)."""
    async with session_factory()() as s:
        counts = await duplicate_pair_counts(s)
    result = {**counts, "scanned_at": datetime.now(UTC).isoformat()}
    _redis().set(SCAN_CACHE_KEY, json.dumps(result))
    return result


def enqueue_duplicate_scan():
    """Queue a duplicate scan on the default queue; while the last one is
    still queued or running, return that job instead of stacking another.
    Returns None when a concurrent call holds the short enqueue lock (it is
    queueing one right now)."""
    from rq import Queue
    from rq.job import Job

    redis = _redis()
    if not redis.set(SCAN_LOCK_KEY, "1", nx=True, ex=SCAN_LOCK_SECONDS):
        return None
    try:
        job_id = redis.get(SCAN_JOB_KEY)
        if job_id is not None:
            job = Job.fetch_many([job_id.decode()], connection=redis)[0]
            if job is not None and job.get_status(refresh=True) in _IN_FLIGHT:
                return job
        job = Queue("default", connection=redis).enqueue(
            SCAN_FUNC, job_timeout=DUPLICATE_SCAN_TIMEOUT,
        )
        redis.set(SCAN_JOB_KEY, job.id)
        return job
    finally:
        redis.delete(SCAN_LOCK_KEY)


async def _run_duplicate_scan() -> dict:
    if "DATABASE_URL" in os.environ:
        init_engine(os.environ["DATABASE_URL"])
    result = await refresh_duplicate_scan()
    logger.info("duplicate scan: %s", result)
    return result


def run_duplicate_scan() -> dict:
    """RQ entrypoint."""
    return run_job(_run_duplicate_scan())


async def run_backfill_batch(
    deadline: float | None = None,
    *, clock: Callable[[], float] = time.monotonic,
) -> dict:
    """Process up to BATCH_MAX_SETS sets, oldest first.

    Returns ``{"processed", "remaining", "errors", "error_ids",
    "fingerprinted", "measured"}``. A set that
    fails gets ``quality_backfill_failed_at`` and drops out of the candidates
    and of ``remaining``, so a permanently broken file cannot stall the
    backfill. ``deadline`` (``time.monotonic()`` value) is checked before each
    set; once passed the batch stops and the unprocessed sets stay in
    ``remaining``. ``clock`` is what ``deadline`` is measured against
    (injectable for tests). A set hard-deleted mid-way is skipped, not an
    error.
    """
    if "DATABASE_URL" in os.environ:
        init_engine(os.environ["DATABASE_URL"])

    pending = and_(
        or_(~_has_current_fingerprint(), LiveSet.quality_measured_at.is_(None)),
        _not_failed(),
    )
    async with session_factory()() as s:
        if await clear_stale_failures(s):
            await s.commit()
        ids = list((await s.execute(
            select(LiveSet.id).where(pending)
            .order_by(LiveSet.created_at, LiveSet.id)
            .limit(BATCH_MAX_SETS)
        )).scalars())

    processed = fingerprinted = measured = 0
    error_ids: list[uuid.UUID] = []
    for live_set_id in ids:
        if deadline is not None and clock() >= deadline:
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
    # fpcalc/ffprobe thread calls. The set can be hard-deleted meanwhile, so
    # every write re-checks it still exists and skips it otherwise.
    async with session_factory()() as s:
        live = await s.get(LiveSet, live_set_id)
        if live is None:
            return False, False
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
            if await s.get(LiveSet, live_set_id) is None:
                return False, False
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


def _redis():
    from redis import Redis

    return Redis.from_url(redis_url())


def enqueue_quality_backfill(**state):
    """Put one backfill slice at the back of the default queue. ``state``
    (cleanup runs only) is passed on to :func:`run_quality_backfill`.
    Records the slice as the chain's latest (:data:`CHAIN_KEY`)."""
    from rq import Queue

    redis = _redis()
    queue = Queue("default", connection=redis)
    if state:
        job = queue.enqueue(JOB_FUNC, job_timeout=QUALITY_BACKFILL_TIMEOUT, kwargs=state)
    else:
        job = queue.enqueue(JOB_FUNC, job_timeout=QUALITY_BACKFILL_TIMEOUT)
    redis.set(CHAIN_KEY, job.id)
    return job


def quality_backfill_in_flight() -> bool:
    """True while a backfill chain is queued or running: its latest slice is
    still queued, or running (it may yet queue the next one). Slice ids
    change from slice to slice, so the chain's latest id is kept in Redis
    instead of a fixed job id (like monitor polls use).

    After a worker crash the slice it was running can still look "started"
    until RQ marks it failed (up to its job timeout, ~1 h); until then a new
    start answers "already running"."""
    from rq.job import Job

    redis = _redis()
    job_id = redis.get(CHAIN_KEY)
    if job_id is None:
        return False
    job = Job.fetch_many([job_id.decode()], connection=redis)[0]
    return job is not None and job.get_status(refresh=True) in _IN_FLIGHT


def start_quality_backfill(*, cleanup: bool = False):
    """Queue the first slice of a backfill run; ``None`` (nothing queued)
    when a chain is already queued or running, or another start holds the
    start lock right now."""
    redis = _redis()
    if not redis.set(START_LOCK_KEY, "1", nx=True, ex=START_LOCK_SECONDS):
        return None
    try:
        if quality_backfill_in_flight():
            return None
        if cleanup:
            return enqueue_quality_backfill(
                cleanup=True, phase="fill", counts=dict.fromkeys(_COUNT_KEYS, 0),
                cursor=None,
            )
        return enqueue_quality_backfill()
    finally:
        redis.delete(START_LOCK_KEY)


async def _run_quality_backfill(
    *, cleanup: bool = False, phase: str = "fill",
    counts: dict | None = None, cursor: list | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> dict:
    """One slice: BATCH_SECONDS or BATCH_MAX_SETS, whichever comes first.

    Without ``cleanup`` only the fill phase runs. With it, the fill slices
    are followed by cleanup slices (``phase="cleanup"``); the last one sends
    the admin summary."""
    counts = {**dict.fromkeys(_COUNT_KEYS, 0), **(counts or {})}
    deadline = clock() + BATCH_SECONDS
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
        _refresh_scan_after_cleanup()
        return res

    res = await run_backfill_batch(deadline=deadline, clock=clock)
    counts["fingerprinted"] += res["fingerprinted"]
    counts["measured"] += res["measured"]
    counts["errors"] += res["errors"]  # sets that failed fingerprinting/measuring
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


def _refresh_scan_after_cleanup() -> None:
    """The cleanup changed which pairs remain: queue a fresh scan for the
    Quality tab (its own job, so this slice ends now). Best effort; the
    cleanup itself is done."""
    try:
        enqueue_duplicate_scan()
    except Exception:
        logger.exception("queueing the duplicate scan after cleanup failed")


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
