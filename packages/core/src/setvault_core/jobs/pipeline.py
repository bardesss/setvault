from __future__ import annotations

import asyncio
import os
import uuid

from setvault_core.db import engine, init_engine, session_factory
from setvault_core.jobs.probe import probe_audio
from setvault_core.models.catalog import LiveSet


async def _run(live_set_id: str) -> None:
    from setvault_core.jobs.fingerprint import fingerprint_audio  # Task F4
    from setvault_core.jobs.normalize import normalize_audio  # Task F6
    from setvault_core.jobs.ready import mark_ready  # Task F6
    from setvault_core.jobs.transcode import transcode_audio  # Task F5
    from setvault_core.jobs.waveform import generate_waveform  # Task F6

    await probe_audio(live_set_id)
    await fingerprint_audio(live_set_id)
    await transcode_audio(live_set_id)
    await normalize_audio(live_set_id)
    await generate_waveform(live_set_id)
    await mark_ready(live_set_id)


def run_pipeline(live_set_id: str) -> None:
    """RQ entrypoint. Chains probe -> fingerprint -> transcode -> normalize -> waveform -> ready."""
    if "DATABASE_URL" in os.environ:
        init_engine(os.environ["DATABASE_URL"])
    try:
        asyncio.run(_run(live_set_id))
    except Exception:
        from setvault_core.progress import ProgressEvent, publish

        publish(ProgressEvent(kind="failed", live_set_id=live_set_id,
                              job_id=live_set_id, progress_pct=0, message="pipeline failed"))

        async def _mark_failed() -> None:
            # This runs in a fresh event loop; the pooled engine from the
            # pipeline's loop holds connections bound to the closed loop, so
            # build a new engine here and dispose it before the loop ends.
            if "DATABASE_URL" in os.environ:
                init_engine(os.environ["DATABASE_URL"])
            try:
                async with session_factory()() as s:
                    live = await s.get(LiveSet, uuid.UUID(live_set_id))
                    if live is not None:
                        live.status = "failed"
                        await s.commit()
            finally:
                await engine().dispose()

        asyncio.run(_mark_failed())
        raise
