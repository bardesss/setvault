"""Admin-triggered backfill: give existing sets a raw chromaprint fingerprint
and a measured audio quality.

Only fills data. It never touches ``duplicate_of``, ``status`` or deleted
state; duplicate cleanup is a separate step. Safe to re-run: only sets that
still lack a current-version fingerprint or a quality measurement are picked
up, oldest first.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
import uuid
from pathlib import Path

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_core.db import init_engine, run_job, session_factory
from setvault_core.jobs.fingerprint import store_fingerprint
from setvault_core.jobs.probe import apply_quality
from setvault_core.models.catalog import LiveSet, MediaRoot, SetFingerprint
from setvault_core.services.audio_match import (
    MATCHER_VERSION,
    compute_raw_fingerprint,
    raw_to_bytes,
)
from setvault_core.services.audio_quality import measure_quality

logger = logging.getLogger(__name__)

QUALITY_BACKFILL_TIMEOUT = "6h"
_MAX_RUNTIME_SECONDS = 5 * 3600  # stop looping well before the 6h RQ timeout


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


async def backfill_candidates(session: AsyncSession) -> dict:
    to_fingerprint = (await session.execute(
        select(func.count()).select_from(LiveSet).where(~_has_current_fingerprint())
    )).scalar_one()
    to_measure = (await session.execute(
        select(func.count()).select_from(LiveSet).where(LiveSet.quality_measured_at.is_(None))
    )).scalar_one()
    return {"to_fingerprint": int(to_fingerprint), "to_measure": int(to_measure)}


async def run_backfill_batch(
    limit: int = 50, skip_ids: set[uuid.UUID] | None = None,
    deadline: float | None = None,
) -> dict:
    """Process up to ``limit`` sets, oldest first.

    Returns ``{"processed", "remaining", "errors", "error_ids"}``. ``skip_ids``
    are sets to leave alone (failed earlier in the same run), so a permanently
    broken file cannot stall the loop; ``remaining`` excludes them too.
    ``deadline`` (``time.monotonic()`` value) is checked before each set; once
    passed the batch stops and the unprocessed sets stay in ``remaining``.
    """
    if "DATABASE_URL" in os.environ:
        init_engine(os.environ["DATABASE_URL"])

    pending = or_(~_has_current_fingerprint(), LiveSet.quality_measured_at.is_(None))
    async with session_factory()() as s:
        q = select(LiveSet.id).where(pending)
        if skip_ids:
            q = q.where(LiveSet.id.not_in(skip_ids))
        ids = list((await s.execute(
            q.order_by(LiveSet.created_at, LiveSet.id).limit(limit)
        )).scalars())

    processed = 0
    error_ids: list[uuid.UUID] = []
    for live_set_id in ids:
        if deadline is not None and time.monotonic() >= deadline:
            break
        try:
            await _backfill_one(live_set_id)
        except Exception:
            logger.warning("quality backfill failed for %s", live_set_id, exc_info=True)
            error_ids.append(live_set_id)
        else:
            processed += 1

    excluded = set(skip_ids or ()) | set(error_ids)
    async with session_factory()() as s:
        rem = select(func.count()).select_from(LiveSet).where(pending)
        if excluded:
            rem = rem.where(LiveSet.id.not_in(excluded))
        remaining = (await s.execute(rem)).scalar_one()
    return {
        "processed": processed, "remaining": int(remaining),
        "errors": len(error_ids), "error_ids": error_ids,
    }


async def _backfill_one(live_set_id: uuid.UUID) -> None:
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
        digest = hashlib.sha256(raw_bytes).hexdigest()
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


async def _run_quality_backfill() -> dict:
    started = time.monotonic()
    totals = {"processed": 0, "errors": 0, "remaining": 0}
    deadline = started + _MAX_RUNTIME_SECONDS
    skip: set[uuid.UUID] = set()
    while True:
        res = await run_backfill_batch(skip_ids=skip, deadline=deadline)
        skip.update(res["error_ids"])
        totals["processed"] += res["processed"]
        totals["errors"] += res["errors"]
        totals["remaining"] = res["remaining"]
        if res["processed"] + res["errors"] == 0 or res["remaining"] == 0:
            break
        if time.monotonic() >= deadline:
            logger.info("quality backfill: time budget reached, re-run to continue")
            break
    logger.info("quality backfill: %s", totals)
    return totals


def run_quality_backfill() -> dict:
    """RQ entrypoint."""
    return run_job(_run_quality_backfill())
