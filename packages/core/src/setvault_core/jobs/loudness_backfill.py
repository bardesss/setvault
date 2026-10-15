"""One-off backfill: re-measure ``normalized_lufs`` for sets that stored the
bogus ``-70.0`` written by the ebur128 parser before it was fixed.

That parser read the first per-frame ``I: -70.0 LUFS`` line instead of the
integrated value in the trailing summary, so every set processed before the
fix holds exactly ``-70.0``. Admin-triggered via
``POST /api/admin/maintenance/remeasure-loudness``; safe to re-run. A
genuinely silent set measures ``-70.0`` again and is just re-scanned.
"""
from __future__ import annotations

import logging
import os

from sqlalchemy import select

from setvault_core.db import init_engine, run_job, session_factory
from setvault_core.jobs.normalize import normalize_audio
from setvault_core.models.catalog import LiveSet

logger = logging.getLogger(__name__)

BOGUS_LUFS = -70.0


async def bogus_loudness_set_ids() -> list[str]:
    async with session_factory()() as s:
        rows = await s.execute(
            select(LiveSet.id).where(LiveSet.normalized_lufs == BOGUS_LUFS)
            .order_by(LiveSet.created_at)
        )
        return [str(i) for i in rows.scalars()]


async def remeasure_bogus_loudness() -> dict:
    """Returns ``{"candidates": N, "remeasured": N, "failed": N}``."""
    if "DATABASE_URL" in os.environ:
        init_engine(os.environ["DATABASE_URL"])

    ids = await bogus_loudness_set_ids()
    remeasured = failed = 0
    for live_set_id in ids:
        try:
            await normalize_audio(live_set_id)
        except Exception:
            # One unreadable original (moved root, deleted file) must not stop
            # the rest of the backfill.
            logger.exception("loudness backfill: re-measure failed for %s", live_set_id)
            failed += 1
        else:
            remeasured += 1
    logger.info("loudness backfill: %d candidates, %d re-measured, %d failed",
                len(ids), remeasured, failed)
    return {"candidates": len(ids), "remeasured": remeasured, "failed": failed}


def run_remeasure_bogus_loudness() -> dict:
    """RQ entrypoint."""
    return run_job(remeasure_bogus_loudness())
