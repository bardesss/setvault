from __future__ import annotations

import asyncio
import os
import subprocess
import uuid
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from setvault_core.db import init_engine, run_job, session_factory
from setvault_core.models.catalog import LiveSet, MediaRoot
from setvault_core.progress import ProgressEvent, publish
from setvault_core.services.loudness import audio_filter, gain_for
from setvault_core.services.storage import path_in_use
from setvault_core.services.system_config import get_config


async def _stream_rel(s: AsyncSession, live: LiveSet) -> str:
    """Where this transcode writes the stream, relative to the media root.

    A re-transcode (e.g. "Re-apply to library") rewrites the set's current
    stream file in place. After a quality upgrade another row (the recycled
    old copy) can name that file, or name ``stream/<id>.opus``
    (services/set_upgrade.py swaps the paths); then a fresh unique name is
    used so the other row's file is never overwritten.
    """
    rel = live.streaming_path or f"stream/{live.id}.opus"
    if await path_in_use(s, live.media_root_id, rel, exclude_live_set_id=live.id):
        return f"stream/{live.id}-{uuid.uuid4().hex[:8]}.opus"
    return rel


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
        host, root_id = Path(root.host_path), root.id
        src = host / live.audio_path
        previous = live.streaming_path
        rel = await _stream_rel(s, live)
        dest = host / rel
        tmp = dest.with_suffix(".opus.tmp")
        dest.parent.mkdir(parents=True, exist_ok=True)

        # Normalize has measured the original by now (pipeline order), so the
        # stream gets a static gain towards the configured target.
        gain_db = gain_for(live.normalized_lufs, (await get_config(s)).loudness_target_lufs)
        af = audio_filter(gain_db)

        publish(ProgressEvent(
            kind="transcode", live_set_id=live_set_id, job_id=live_set_id,
            progress_pct=70, message="encoding opus 128k",
        ))
        await asyncio.to_thread(
            subprocess.run,
            [
                "ffmpeg", "-y", "-i", str(src),
                *(["-af", af] if af else []),
                "-c:a", "libopus", "-b:a", "128k", "-vbr", "on",
                "-application", "audio",
                "-ac", "2", "-ar", "48000",
                "-f", "opus", str(tmp),
            ],
            check=True, capture_output=True,
        )
        tmp.replace(dest)

        live.streaming_path = rel
        live.stream_gain_db = gain_db
        await s.commit()
        # The old file, once no row names it any more (the new one has
        # replaced it in the row just committed).
        if previous and previous != rel and not await path_in_use(
            s, root_id, previous, exclude_live_set_id=None,
        ):
            (host / previous).unlink(missing_ok=True)
        publish(ProgressEvent(
            kind="transcode", live_set_id=live_set_id, job_id=live_set_id,
            progress_pct=80, message="opus ready",
        ))


def transcode_audio_sync(live_set_id: str) -> None:
    run_job(transcode_audio(live_set_id))
