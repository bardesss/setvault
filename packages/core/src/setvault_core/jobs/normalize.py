from __future__ import annotations

import asyncio
import os
import subprocess
import uuid
from pathlib import Path

from setvault_core.db import init_engine, session_factory
from setvault_core.models.catalog import LiveSet, MediaRoot
from setvault_core.progress import ProgressEvent, publish


async def normalize_audio(live_set_id: str) -> None:
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

        publish(ProgressEvent(
            kind="normalize", live_set_id=live_set_id, job_id=live_set_id,
            progress_pct=70, message="EBU R128 scan",
        ))
        cmd = [
            "ffmpeg", "-hide_banner", "-i", str(src),
            "-af", "ebur128=peak=true",
            "-f", "null", "-",
        ]
        out = await asyncio.to_thread(
            subprocess.run, cmd,
            check=True, capture_output=True, text=True,
        )
        lufs = _extract_integrated_loudness(out.stderr)
        live.normalized_lufs = lufs
        await s.commit()
        publish(ProgressEvent(
            kind="normalize", live_set_id=live_set_id, job_id=live_set_id,
            progress_pct=80, message=f"integrated loudness {lufs} LUFS",
        ))


def _extract_integrated_loudness(stderr: str) -> float | None:
    # ebur128 logs a running "I: -70.0 LUFS" on every frame; the real value is
    # the integrated loudness in the trailing "Summary:" block.
    _, sep, summary = stderr.rpartition("Summary:")
    if not sep:
        return None
    for line in summary.splitlines():
        if "I:" in line and "LUFS" in line:
            try:
                return float(line.split("I:")[1].split("LUFS")[0].strip())
            except (IndexError, ValueError):
                continue
    return None


def normalize_audio_sync(live_set_id: str) -> None:
    asyncio.run(normalize_audio(live_set_id))
