"""Admin-triggered "Re-apply to library": re-transcode the stream of every
published set whose stored ``stream_gain_db`` is more than 0.5 dB away from
the gain the current loudness target implies (P2a A3).

Enqueued by ``POST /api/admin/maintenance/regain`` on the ``low`` queue; never
run automatically. Each set goes through the normal ``transcode_audio``
(tmp file, then ``replace``; one commit per set), so the stream and the
recorded gain can't drift from what new uploads get. Resumable: a re-run
skips every set already at its gain.
"""
from __future__ import annotations

import logging
import os

from sqlalchemy import select

from setvault_core.db import init_engine, run_job, session_factory
from setvault_core.jobs.transcode import transcode_audio
from setvault_core.models.catalog import LiveSet
from setvault_core.services.loudness import gain_for
from setvault_core.services.system_config import get_config

logger = logging.getLogger(__name__)

REGAIN_THRESHOLD_DB = 0.5
REGAIN_JOB_FUNC = "setvault_core.jobs.regain.run_regain_library"
REGAIN_JOB_TIMEOUT = "6h"


async def regain_library() -> dict:
    """Returns ``{"checked": N, "regained": N, "failed": N}``."""
    if "DATABASE_URL" in os.environ:
        init_engine(os.environ["DATABASE_URL"])

    async with session_factory()() as s:
        target = (await get_config(s)).loudness_target_lufs
        rows = (await s.execute(
            select(LiveSet.id, LiveSet.normalized_lufs, LiveSet.stream_gain_db)
            .where(
                LiveSet.deleted_at.is_(None),
                LiveSet.status == "published",
                LiveSet.streaming_path.is_not(None),
            )
            .order_by(LiveSet.created_at)
        )).all()

    due = [
        str(sid) for sid, lufs, applied in rows
        if abs(gain_for(lufs, target) - (applied or 0.0)) > REGAIN_THRESHOLD_DB
    ]
    regained = failed = 0
    for live_set_id in due:
        try:
            await transcode_audio(live_set_id)
        except Exception:
            # One unreadable original (moved root, deleted file) must not stop
            # the rest of the library.
            logger.exception("regain: re-transcode failed for %s", live_set_id)
            failed += 1
        else:
            regained += 1
    logger.info("regain: %d checked, %d re-gained, %d failed", len(rows), regained, failed)
    return {"checked": len(rows), "regained": regained, "failed": failed}


def run_regain_library() -> dict:
    """RQ entrypoint."""
    return run_job(regain_library())
