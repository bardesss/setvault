from __future__ import annotations

import asyncio
import os
import subprocess
import uuid
from pathlib import Path

from setvault_core.db import init_engine, run_job, session_factory
from setvault_core.models.catalog import LiveSet, MediaRoot
from setvault_core.progress import ProgressEvent, publish


async def transcode_audio(live_set_id: str) -> None:
    if "DATABASE_URL" in os.environ:
        init_engine(os.environ["DATABASE_URL"])

    async with session_factory()() as s:
        live = await s.get(LiveSet, uuid.UUID(live_set_id))
        if live is None:
            raise RuntimeError(f"LiveSet {live_set_id} missing")
        root = await s.get(MediaRoot, live.media_root_id)
        if root is None:
            raise RuntimeError("MediaRoot vanished")
        src = Path(root.host_path) / live.audio_path
        rel = f"stream/{live.id}.opus"
        dest = Path(root.host_path) / rel
        tmp = dest.with_suffix(".opus.tmp")
        dest.parent.mkdir(parents=True, exist_ok=True)

        publish(ProgressEvent(
            kind="transcode", live_set_id=live_set_id, job_id=live_set_id,
            progress_pct=40, message="encoding opus 128k",
        ))
        await asyncio.to_thread(
            subprocess.run,
            [
                "ffmpeg", "-y", "-i", str(src),
                "-c:a", "libopus", "-b:a", "128k", "-vbr", "on",
                "-application", "audio",
                "-ac", "2", "-ar", "48000",
                "-f", "opus", str(tmp),
            ],
            check=True, capture_output=True,
        )
        tmp.replace(dest)

        live.streaming_path = rel
        await s.commit()
        publish(ProgressEvent(
            kind="transcode", live_set_id=live_set_id, job_id=live_set_id,
            progress_pct=60, message="opus ready",
        ))


def transcode_audio_sync(live_set_id: str) -> None:
    run_job(transcode_audio(live_set_id))
