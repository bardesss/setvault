from __future__ import annotations

import os
import uuid

from setvault_core import triggers
from setvault_core.db import init_engine, run_job, session_factory
from setvault_core.jobs.probe import probe_audio
from setvault_core.models.catalog import LiveSet

# RQ's default job timeout is 180s, far too short for a multi-hour set.
# Every enqueue of run_pipeline must pass this. Room for probe's quality
# check (180 s), two fpcalc runs (900 s cap each), normalise and transcode.
PIPELINE_JOB_TIMEOUT = "1h"


async def _run(live_set_id: str) -> None:
    from setvault_core.jobs.fingerprint import fingerprint_audio  # Task F4
    from setvault_core.jobs.normalize import normalize_audio  # Task F6
    from setvault_core.jobs.ready import mark_ready  # Task F6
    from setvault_core.jobs.transcode import transcode_audio  # Task F5
    from setvault_core.jobs.waveform import generate_waveform  # Task F6

    await probe_audio(live_set_id)
    await fingerprint_audio(live_set_id)
    # Measure the original first: transcode applies the gain towards the
    # loudness target (P2a A3).
    await normalize_audio(live_set_id)
    await transcode_audio(live_set_id)
    await generate_waveform(live_set_id)
    async with session_factory()() as s:
        live = await s.get(LiveSet, uuid.UUID(live_set_id))
        source_type = live.source_type if live is not None else None
    # Upgrade history records how a better copy arrived.
    trigger = triggers.WATCH_FOLDER if source_type == "watch_folder" else triggers.UPLOAD
    await mark_ready(live_set_id, trigger=trigger)


def run_pipeline(live_set_id: str) -> None:
    """RQ entrypoint. Chains probe -> fingerprint -> normalize -> transcode -> waveform -> ready."""
    if "DATABASE_URL" in os.environ:
        init_engine(os.environ["DATABASE_URL"])
    try:
        run_job(_run(live_set_id))
    except Exception:
        from setvault_core.progress import ProgressEvent, publish

        publish(ProgressEvent(kind="failed", live_set_id=live_set_id,
                              job_id=live_set_id, progress_pct=0, message="pipeline failed"))

        async def _mark_failed() -> None:
            # run_job disposed the pipeline loop's pool, so the engine opens
            # fresh connections on this loop.
            async with session_factory()() as s:
                live = await s.get(LiveSet, uuid.UUID(live_set_id))
                if live is not None:
                    live.status = "failed"
                    await s.commit()

        run_job(_mark_failed())
        raise
