from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_core.db import init_engine, run_job, session_factory
from setvault_core.models.catalog import LiveSet, MediaRoot
from setvault_core.progress import ProgressEvent, publish
from setvault_core.services.loudness import audio_filter, gain_for
from setvault_core.services.storage import path_in_use
from setvault_core.services.system_config import get_config

logger = logging.getLogger(__name__)


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


def _unlink(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("transcode: failed to unlink %s: %s", path, exc)


async def transcode_audio(live_set_id: str) -> None:
    """Encode the set's stream and swap it in.

    ffmpeg runs without a row lock, into a temp file of its own. Afterwards
    the row is re-read under ``SELECT ... FOR UPDATE``: a quality upgrade
    (services/set_upgrade.apply_upgrade) may have swapped the audio columns
    meanwhile, and the stream file this job meant to write may then belong
    to the recycled old copy. If the row no longer holds the audio that was
    encoded, the new stream is dropped (the upgrade carries the arrival's
    own stream); otherwise the target path is decided against the locked
    state and the file swapped in before the commit.
    """
    if "DATABASE_URL" in os.environ:
        init_engine(os.environ["DATABASE_URL"])

    set_id = uuid.UUID(live_set_id)
    async with session_factory()() as s:
        live = await s.get(LiveSet, set_id)
        if live is None:
            raise RuntimeError(f"LiveSet {live_set_id} missing")
        root = await s.get(MediaRoot, live.media_root_id)
        if root is None:
            raise RuntimeError("MediaRoot vanished")
        host, root_id = Path(root.host_path), root.id
        audio_path, was_deleted = live.audio_path, live.deleted_at is not None
        src = host / audio_path
        # Normalize has measured the original by now (pipeline order), so the
        # stream gets a static gain towards the configured target. Read with
        # audio_path in one statement: the measurement of the encoded audio.
        gain_db = gain_for(live.normalized_lufs, (await get_config(s)).loudness_target_lufs)
        # End the read transaction: no lock or snapshot is held while encoding.
        await s.commit()

    af = audio_filter(gain_db)
    stream_dir = host / "stream"
    stream_dir.mkdir(parents=True, exist_ok=True)
    # Unique per run, so two transcodes of one set never share a temp file.
    tmp = stream_dir / f".{set_id}.{uuid.uuid4().hex}.opus.tmp"
    try:
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

        async with session_factory()() as s:
            try:
                live = (await s.execute(
                    select(LiveSet).where(LiveSet.id == set_id)
                    .with_for_update(of=LiveSet)
                    .execution_options(populate_existing=True)
                )).scalar_one_or_none()
                if (
                    live is None
                    or live.audio_path != audio_path
                    or live.media_root_id != root_id
                    or (live.deleted_at is not None and not was_deleted)
                ):
                    # Swapped by an upgrade (or replaced, recycled, deleted)
                    # while encoding: this stream is of audio the row no
                    # longer has. Touch no stream file.
                    logger.info(
                        "transcode %s: audio changed while encoding %s; "
                        "discarding the new stream", live_set_id, audio_path,
                    )
                    await s.rollback()
                    return
                previous = live.streaming_path
                rel = await _stream_rel(s, live)
                (host / rel).parent.mkdir(parents=True, exist_ok=True)
                tmp.replace(host / rel)
                live.streaming_path = rel
                live.stream_gain_db = gain_db
                await s.commit()
            except Exception:
                await s.rollback()
                raise
            # The old file, once no row names it any more (the new one has
            # replaced it in the row just committed).
            if previous and previous != rel and not await path_in_use(
                s, root_id, previous, exclude_live_set_id=None,
            ):
                _unlink(host / previous)
    finally:
        # Gone after a successful replace; otherwise this run's leftover.
        _unlink(tmp)

    publish(ProgressEvent(
        kind="transcode", live_set_id=live_set_id, job_id=live_set_id,
        progress_pct=80, message="opus ready",
    ))


def transcode_audio_sync(live_set_id: str) -> None:
    run_job(transcode_audio(live_set_id))
