from __future__ import annotations

import asyncio
import json
import os
import subprocess
import uuid
from pathlib import Path

from setvault_core.db import init_engine, run_job, session_factory
from setvault_core.models.catalog import LiveSet, MediaRoot
from setvault_core.progress import ProgressEvent, publish


async def probe_audio(live_set_id: str) -> None:
    if "DATABASE_URL" in os.environ:
        init_engine(os.environ["DATABASE_URL"])

    async with session_factory()() as s:
        live = await s.get(LiveSet, uuid.UUID(live_set_id))
        if live is None:
            raise RuntimeError(f"LiveSet {live_set_id} missing")
        root = await s.get(MediaRoot, live.media_root_id)
        if root is None:
            raise RuntimeError("MediaRoot vanished")
        path = Path(root.host_path) / live.audio_path

        publish(ProgressEvent(kind="probe", live_set_id=live_set_id, job_id=live_set_id,
                              progress_pct=5, message="probing audio"))
        cmd = ["ffprobe", "-v", "error", "-show_format", "-show_streams",
               "-of", "json", str(path)]
        out = await asyncio.to_thread(
            subprocess.run, cmd,
            check=True, capture_output=True, text=True,
        )
        info = json.loads(out.stdout)
        duration = float(info.get("format", {}).get("duration", 0))
        live.duration_seconds = round(duration)
        await s.commit()

        publish(ProgressEvent(kind="probe", live_set_id=live_set_id, job_id=live_set_id,
                              progress_pct=10, message=f"duration={live.duration_seconds}s"))


def probe_audio_sync(live_set_id: str) -> None:
    run_job(probe_audio(live_set_id))
