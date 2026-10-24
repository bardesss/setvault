from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_core.db import init_engine, run_job, session_factory
from setvault_core.models.catalog import LiveSet, MediaRoot
from setvault_core.progress import ProgressEvent, publish
from setvault_core.services.loudness import audio_filter, gain_for
from setvault_core.services.storage import path_in_use
from setvault_core.services.system_config import get_config

logger = logging.getLogger(__name__)

TranscodeOutcome = Literal["done", "discarded"]
# Encodes per call: a rename or root move during an encode costs a re-encode,
# bounded so a set whose audio keeps moving can't loop forever.
MAX_ATTEMPTS = 3


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


@dataclass(frozen=True)
class _Snapshot:
    """The row as read (unlocked) before an encode."""
    host: Path
    root_id: uuid.UUID
    audio_path: str
    streaming_path: str | None
    gain_db: float


async def _read(set_id: uuid.UUID, *, missing_ok: bool) -> _Snapshot | None:
    """None when the set is recycled (or gone, with ``missing_ok``): a
    recycled set needs no new stream. Ends its transaction, so no lock or
    snapshot is held while encoding."""
    async with session_factory()() as s:
        live = await s.get(LiveSet, set_id)
        if live is None:
            if missing_ok:
                return None
            raise RuntimeError(f"LiveSet {set_id} missing")
        if live.deleted_at is not None:
            return None
        root = await s.get(MediaRoot, live.media_root_id)
        if root is None:
            raise RuntimeError("MediaRoot vanished")
        # Normalize has measured the original by now (pipeline order), so the
        # stream gets a static gain towards the configured target. Read with
        # audio_path in one row: the measurement of the audio being encoded.
        snap = _Snapshot(
            host=Path(root.host_path), root_id=root.id, audio_path=live.audio_path,
            streaming_path=live.streaming_path,
            gain_db=gain_for(live.normalized_lufs, (await get_config(s)).loudness_target_lufs),
        )
        await s.commit()
    return snap


async def _encode(snap: _Snapshot, tmp: Path, live_set_id: str) -> None:
    af = audio_filter(snap.gain_db)
    publish(ProgressEvent(
        kind="transcode", live_set_id=live_set_id, job_id=live_set_id,
        progress_pct=70, message="encoding opus 128k",
    ))
    await asyncio.to_thread(
        subprocess.run,
        [
            "ffmpeg", "-y", "-i", str(snap.host / snap.audio_path),
            *(["-af", af] if af else []),
            "-c:a", "libopus", "-b:a", "128k", "-vbr", "on",
            "-application", "audio",
            "-ac", "2", "-ar", "48000",
            "-f", "opus", str(tmp),
        ],
        check=True, capture_output=True,
    )


async def _swap_in(
    set_id: uuid.UUID, snap: _Snapshot, tmp: Path,
) -> Literal["done", "discarded", "retry"]:
    """Re-read the row under ``SELECT ... FOR UPDATE`` and, if it still holds
    the encoded audio, move ``tmp`` into its stream path and commit.

    ``"discarded"``: the row is gone or recycled, or its ``streaming_path``
    changed. A quality upgrade (services/set_upgrade.apply_upgrade) always
    changes it, since the arrival brings its own stream; the stream file this
    job meant to write may then belong to the recycled old copy.
    ``"retry"``: only the audio file moved (a rename, a root move); the
    encode is of the right audio but the row now names other bytes or
    another root, so encode again from the current state.
    """
    async with session_factory()() as s:
        try:
            live = (await s.execute(
                select(LiveSet).where(LiveSet.id == set_id)
                .with_for_update(of=LiveSet)
                .execution_options(populate_existing=True)
            )).scalar_one_or_none()
            if live is None or live.deleted_at is not None:
                logger.info("transcode %s: set gone or recycled while encoding; "
                            "discarding the new stream", set_id)
                await s.rollback()
                return "discarded"
            if live.streaming_path != snap.streaming_path:
                logger.info("transcode %s: stream changed while encoding (%s -> %s); "
                            "discarding the new stream",
                            set_id, snap.streaming_path, live.streaming_path)
                await s.rollback()
                return "discarded"
            if live.audio_path != snap.audio_path or live.media_root_id != snap.root_id:
                await s.rollback()
                return "retry"
            previous = live.streaming_path
            rel = await _stream_rel(s, live)
            (snap.host / rel).parent.mkdir(parents=True, exist_ok=True)
            # A rename within the stream dir: quick, and must happen under the lock.
            tmp.replace(snap.host / rel)  # noqa: ASYNC240
            live.streaming_path = rel
            live.stream_gain_db = snap.gain_db
            await s.commit()
        except Exception:
            await s.rollback()
            raise

        # The old file, once no row names it any more (the new one has
        # replaced it in the row just committed). The stream is committed:
        # a failure here must not fail the job.
        try:
            if previous and previous != rel and not await path_in_use(
                s, snap.root_id, previous, exclude_live_set_id=None,
            ):
                _unlink(snap.host / previous)
        except Exception:
            logger.exception("transcode %s: post-commit cleanup of %s failed", set_id, previous)
    return "done"


async def transcode_audio(live_set_id: str) -> TranscodeOutcome:
    """Encode the set's stream and swap it in.

    ffmpeg runs without a row lock, into a temp file of its own; the row is
    then re-checked under lock (see :func:`_swap_in`). Returns ``"done"``, or
    ``"discarded"`` when no stream was committed: the set is recycled or gone,
    an upgrade swapped its stream meanwhile, or its audio kept moving for
    ``MAX_ATTEMPTS`` encodes.
    """
    if "DATABASE_URL" in os.environ:
        init_engine(os.environ["DATABASE_URL"])

    set_id = uuid.UUID(live_set_id)
    for attempt in range(1, MAX_ATTEMPTS + 1):
        snap = await _read(set_id, missing_ok=attempt > 1)
        if snap is None:
            logger.info("transcode %s: set gone or recycled; no stream written", live_set_id)
            return "discarded"
        stream_dir = snap.host / "stream"
        stream_dir.mkdir(parents=True, exist_ok=True)
        # Unique per run, so two transcodes of one set never share a temp file.
        tmp = stream_dir / f".{set_id}.{uuid.uuid4().hex}.opus.tmp"
        try:
            await _encode(snap, tmp, live_set_id)
            result = await _swap_in(set_id, snap, tmp)
        finally:
            # Gone after a successful replace; otherwise this run's leftover.
            _unlink(tmp)
        if result == "done":
            publish(ProgressEvent(
                kind="transcode", live_set_id=live_set_id, job_id=live_set_id,
                progress_pct=80, message="opus ready",
            ))
            return "done"
        if result == "discarded":
            return "discarded"
        logger.info("transcode %s: audio moved while encoding %s; re-encoding (attempt %d/%d)",
                    live_set_id, snap.audio_path, attempt, MAX_ATTEMPTS)
    logger.warning("transcode %s: audio kept moving; gave up after %d encodes",
                   live_set_id, MAX_ATTEMPTS)
    return "discarded"


def transcode_audio_sync(live_set_id: str) -> None:
    run_job(transcode_audio(live_set_id))
