"""RQ entry point for URL rips.

Pipeline:

    queued -> probing -> downloading -> probing (ffprobe + chromaprint dedup)
           -> transcoding -> normalizing -> waveform -> ready

On any step's exception: status=failed with error_text, tmp dir purged, RipJob row
gets finished_at.

The probe/fingerprint/transcode/normalize/waveform/ready stages reuse the Phase 2B job
functions which take a live_set_id and update LiveSet.status + emit
ProgressEvents on their own. We just update the RipJob row in between so the
Jobs drawer reflects the active phase.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_core import triggers
from setvault_core.db import init_engine, run_job, session_factory
from setvault_core.models.catalog import LiveSet, MediaRoot
from setvault_core.models.upgrades import SetUpgradeEvent
from setvault_core.models.url_rip import RipJob
from setvault_core.services.catalog import slugify
from setvault_core.services.set_upgrade import build_upgrade_event, event_audio
from setvault_core.services.storage import path_in_use

if TYPE_CHECKING:
    from setvault_core.services.upgrade_decision import Decision

logger = logging.getLogger(__name__)

DATABASE_URL_ENV = "DATABASE_URL"


_ERROR_TEXT_MAX = 500

# Prefer a lossless stream when a source offers one (Bandcamp free downloads,
# Internet Archive originals); sources without one fall back to bestaudio.
_AUDIO_FORMAT = (
    "bestaudio[acodec=flac]/bestaudio[ext=flac]/bestaudio[acodec=alac]/"
    "bestaudio[ext=wav]/bestaudio[ext=aiff]/bestaudio/best"
)

# Download + the full pipeline run inside one RQ job; RQ's 180s default kills
# any real-length set. Every enqueue of run_rip_job must pass this.
RIP_JOB_TIMEOUT = "1h"

# Refuse downloads bigger than this (yt-dlp skips them). A six-hour lossless
# set is ~3 GB; anything larger is almost certainly not a single set.
MAX_DOWNLOAD_BYTES = 4 * 1024**3


def _error_text(exc: BaseException) -> str:
    """Build the user-visible error_text for a failed rip.

    SetVault is self-hosted and single-user, so the only person who sees this
    string is the operator debugging their own instance. We surface the real
    exception (type + message, truncated) instead of a coarse category — a bare
    "error during rip" leaves nothing to act on. The full traceback is still
    written to the worker log via logger.exception.
    """
    # UnsupportedUrlError's message is constant and already user-friendly.
    try:
        from setvault_core.services.url_rip import UnsupportedUrlError
        if isinstance(exc, UnsupportedUrlError):
            return "URL is not on the supported-platforms allowlist"
    except Exception:  # noqa: S110 — best-effort import; fall through if unavailable
        pass
    # subprocess failures (ffmpeg/ffprobe/audiowaveform) carry the actionable
    # detail in stderr, not in str(exc) ("returned non-zero exit status 1").
    if isinstance(exc, subprocess.CalledProcessError):
        stderr = exc.stderr
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", "replace")
        cmd = exc.cmd[0] if isinstance(exc.cmd, (list, tuple)) and exc.cmd else exc.cmd
        tail = (stderr or "").strip()[-_ERROR_TEXT_MAX:]
        return f"{cmd} failed (exit {exc.returncode}): {tail or '(no stderr)'}"[:_ERROR_TEXT_MAX]
    detail = str(exc).strip()
    label = exc.__class__.__name__
    text = f"{label}: {detail}" if detail else label
    return text[:_ERROR_TEXT_MAX]


async def _set_status(
    session: AsyncSession, job: RipJob, status: str,
    *, progress_pct: int | None = None, message: str | None = None,
) -> None:
    job.status = status
    if progress_pct is not None:
        job.progress_pct = progress_pct
    if message is not None:
        job.message = message
    if status == "downloading" and job.started_at is None:
        job.started_at = datetime.now(UTC)
    if status in {"ready", "failed"}:
        job.finished_at = datetime.now(UTC)
    job.updated_at = datetime.now(UTC)
    await session.flush()
    await session.commit()


async def _download(job: RipJob, tmp_dir: Path) -> Path:
    """Run yt-dlp to fetch bestaudio. Returns the path to the downloaded file.

    Re-runs the SSRF allowlist gate before shelling out to yt-dlp; the row's
    source_url could in principle have been edited between submit_rip()
    and worker pickup.
    """
    import yt_dlp

    from setvault_core.services.url_rip import require_supported_url
    from setvault_core.services.ytdlp_cookies import ytdlp_cookie_opts

    require_supported_url(job.source_url)

    output_template = str(tmp_dir / f"{job.id}.%(ext)s")
    rejected: list[str] = []

    def _match_filter(info: dict, *, incomplete: bool = False) -> str | None:
        # The submit-time probe already refuses live streams, but a scheduled
        # premiere can go live between submit and worker pickup.
        if info.get("is_live") or info.get("live_status") in {"is_live", "is_upcoming"}:
            rejected.append("live streams can't be ripped")
            return rejected[-1]
        return None

    def _cap_written_bytes(progress: dict) -> None:
        # max_filesize only applies when the size is known up front; streamed
        # and fragmented (HLS/DASH) downloads must be stopped on what's
        # actually been written.
        if (progress.get("downloaded_bytes") or 0) > MAX_DOWNLOAD_BYTES:
            raise RuntimeError(
                f"download exceeded the {MAX_DOWNLOAD_BYTES // 1024**3} GiB limit",
            )

    ydl_opts = {
        "format": _AUDIO_FORMAT,
        "outtmpl": output_template,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "noplaylist": True,
        "max_filesize": MAX_DOWNLOAD_BYTES,
        "match_filter": _match_filter,
        "progress_hooks": [_cap_written_bytes],
    }

    def _run() -> dict:
        with ytdlp_cookie_opts() as cookie_opts, \
                yt_dlp.YoutubeDL({**ydl_opts, **cookie_opts}) as ydl:
            return ydl.extract_info(job.source_url, download=True)

    info = await asyncio.to_thread(_run)
    if rejected:
        raise RuntimeError(rejected[0])
    info = info or {}
    filepath = info.get("filepath") or info.get("_filename")
    # ASYNC240: trivial stat + listdir on a freshly-created tmp dir we own —
    # blocking time is bounded and matches the precedent in apps/web uploads.py.
    if not filepath or not Path(filepath).exists():  # noqa: ASYNC240
        candidates = list(tmp_dir.glob(f"{job.id}.*"))  # noqa: ASYNC240
        if not candidates:
            raise RuntimeError(
                "yt-dlp produced no file (larger than the "
                f"{MAX_DOWNLOAD_BYTES // 1024**3} GiB limit, or nothing to download)",
            )
        filepath = str(candidates[0])
    return Path(filepath)


async def _create_draft_live_set(
    session: AsyncSession, job: RipJob, *, root: MediaRoot, audio_relpath: str,
) -> LiveSet:
    """Materialise a draft LiveSet for this rip pointing at the downloaded file."""
    meta = job.probed_metadata or {}
    title = meta.get("title") or "(untitled)"
    slug = slugify(title, fallback="untitled", max_len=60) + "-" + uuid.uuid4().hex[:6]
    if job.submitted_by is None:
        raise RuntimeError("rip job has no submitted_by user")
    live = LiveSet(
        slug=slug,
        title=title,
        media_root_id=root.id,
        audio_path=audio_relpath,
        status="draft",
        source_type="url_rip",
        source_url=job.source_url,
        source_external_id=job.source_external_id,
        uploaded_by=job.submitted_by,
    )
    session.add(live)
    await session.flush()
    job.live_set_id = live.id
    await session.flush()
    await session.commit()
    return live


async def _discard_partial_rip(
    session: AsyncSession, job: RipJob, root: MediaRoot,
    *, created_live_set_id: uuid.UUID | None,
) -> None:
    """Undo what a rip that failed before publishing left behind: the draft
    LiveSet (nothing lists non-published sets, so it would sit invisible
    forever, plus one more per retry) and its files under the root. Best
    effort; the RipJob row itself stays so the user sees the failure.

    Only the set this run created is a candidate, and only while it is still
    an unpublished, non-recycled draft that no upgrade has touched. A failure
    after a committed quality swap (services/set_upgrade) leaves the job
    pointing at the upgraded target and the created row holding the recycled
    old copy; neither may be hard-deleted here. Files another set references
    are always kept.
    """
    host = Path(root.host_path)
    deleted_id: uuid.UUID | None = None
    live = None
    if created_live_set_id is not None:
        live = await session.get(LiveSet, created_live_set_id, populate_existing=True)
    if live is not None:
        upgraded = await session.scalar(select(exists().where(
            SetUpgradeEvent.live_set_id == live.id, SetUpgradeEvent.outcome == "upgraded",
        )))
        if live.status != "draft" or live.deleted_at is not None or upgraded:
            logger.warning("rip discard: keeping set %s (status=%s, recycled=%s, upgraded=%s)",
                           live.id, live.status, live.deleted_at is not None, bool(upgraded))
        else:
            deleted_id = live.id
            # RipJob.live_set_id cascades; keep the job row by detaching it.
            if job.live_set_id == live.id:
                job.live_set_id = None
                await session.flush()
            for rel in (live.streaming_path, live.waveform_path):
                if rel and not await path_in_use(
                    session, live.media_root_id, rel, exclude_live_set_id=deleted_id,
                ):
                    (host / rel).unlink(missing_ok=True)
            await session.delete(live)
    await _remove_rip_dir(session, root, job.id, exclude_live_set_id=deleted_id)
    await session.commit()


async def _remove_rip_dir(
    session: AsyncSession, root: MediaRoot, job_id: uuid.UUID,
    *, exclude_live_set_id: uuid.UUID | None,
) -> None:
    """Delete ``originals/<job_id>/`` except files another LiveSet still
    references (a quality upgrade can move a rip's audio into another set),
    then drop the directories left empty."""
    host = Path(root.host_path)
    rip_dir = host / "originals" / str(job_id)
    if not rip_dir.is_dir():
        return
    for dirpath, _dirnames, filenames in os.walk(rip_dir, topdown=False):
        for name in filenames:
            path = Path(dirpath) / name
            rel = path.relative_to(host).as_posix()
            if await path_in_use(session, root.id, rel, exclude_live_set_id=exclude_live_set_id):
                logger.info("rip discard: keeping %s, another set uses it", rel)
                continue
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:
                logger.warning("rip discard: failed to unlink %s: %s", path, exc)
        try:
            os.rmdir(dirpath)
        except OSError:
            pass  # not empty: something we kept


async def _run_rip_job(session: AsyncSession, job_id: uuid.UUID) -> None:
    """The pipeline itself. Separated from the RQ entry point for testing."""
    job = await session.get(RipJob, job_id)
    if job is None:
        logger.warning("rip job %s not found", job_id)
        return

    tmp_dir = Path(tempfile.mkdtemp(prefix=f"setvault-rip-{job_id}-"))
    root: MediaRoot | None = None
    created_live_set_id: uuid.UUID | None = None
    finished = False
    try:
        # Same rule as uploads: a disabled root never receives new ingests.
        root = (await session.execute(
            select(MediaRoot).where(
                MediaRoot.default_for_ingest.is_(True), MediaRoot.enabled.is_(True),
            )
            .order_by(MediaRoot.created_at).limit(1)
        )).scalar_one_or_none()
        if root is None:
            job.error_text = "no default-for-ingest MediaRoot configured"
            await _set_status(session, job, "failed",
                              message="no default ingest root")
            return

        await _set_status(session, job, "probing", progress_pct=5,
                          message="re-probing URL")
        # Probe already ran in submit_rip; nothing to repeat.

        await _set_status(session, job, "downloading", progress_pct=15,
                          message="downloading audio")
        downloaded = await _download(job, tmp_dir)

        # Move the file into the originals/ subtree under the default root.
        # shutil.move (not Path.replace) because the OS temp dir and the media
        # root are frequently on different mounts (container fs vs. /data
        # volume), where an atomic rename raises OSError(EXDEV).
        originals_dir = Path(root.host_path) / "originals" / str(job.id)
        originals_dir.mkdir(parents=True, exist_ok=True)
        final_original = originals_dir / downloaded.name
        shutil.move(str(downloaded), str(final_original))
        audio_relpath = str(final_original.relative_to(root.host_path)).replace("\\", "/")

        live = await _create_draft_live_set(
            session, job, root=root, audio_relpath=audio_relpath,
        )
        # Remember what this run created; job.live_set_id can be repointed
        # later (an upgrade swap moves it to the target).
        created_live_set_id = live.id
        live_set_id = str(live.id)

        # The downstream stages each open their own session via session_factory()
        # and emit ProgressEvents tied to the LiveSet. We just update the RipJob
        # marker between phases so the Jobs drawer reflects what's running.
        from setvault_core.jobs.fingerprint import fingerprint_audio
        from setvault_core.jobs.normalize import normalize_audio
        from setvault_core.jobs.probe import probe_audio
        from setvault_core.jobs.ready import finish_arrival
        from setvault_core.jobs.transcode import transcode_audio
        from setvault_core.jobs.waveform import generate_waveform

        await _set_status(session, job, "probing", progress_pct=30,
                          message="probing audio")
        await probe_audio(live_set_id)

        # Same chromaprint dedup as uploads and watch-folder ingest: flags
        # duplicate_of (or restores a recycled original) and records the
        # SetFingerprint that later rips/uploads and upgrade matching check.
        # An upgrade attempt is compared with its target only.
        await _set_status(session, job, "probing", progress_pct=38,
                          message="fingerprinting")
        if job.upgrade_target_set_id is not None:
            # R28: judged against its target only (no library-wide match,
            # no recycled-original restore).
            await fingerprint_audio(live_set_id, upgrade_target_id=job.upgrade_target_set_id)
        else:
            await fingerprint_audio(live_set_id)

        trigger = job.trigger or triggers.URL_RIP
        candidate = {"candidate_source_kind": job.source_platform,
                     "candidate_external_id": job.source_external_id}
        if job.upgrade_target_set_id is not None:
            # An upgrade attempt that can't upgrade its target (different
            # audio, not better, target gone or locked) is discarded now,
            # before the transcode/normalize/waveform work. One the fingerprint
            # stage already recycled (R1) ends here too, as held.
            early = await _discard_unless_upgrade(
                live.id, target_id=job.upgrade_target_set_id, trigger=trigger, **candidate,
            )
            if early is not None:
                # Discarded (row and files gone) or recycled (the purge job
                # owns it): nothing for _discard_partial_rip to undo.
                finished = True
                await session.refresh(job)
                await _set_status(session, job, "ready", progress_pct=100,
                                  message=early.message)
                return

        # Measure the original first: transcode applies the gain towards the
        # loudness target (P2a A3).
        await _set_status(session, job, "normalizing", progress_pct=45,
                          message="EBU R128 scan")
        await normalize_audio(live_set_id)

        await _set_status(session, job, "transcoding", progress_pct=65,
                          message="encoding Opus")
        await transcode_audio(live_set_id)

        await _set_status(session, job, "waveform", progress_pct=85,
                          message="rendering waveform")
        await generate_waveform(live_set_id)

        # Publishes, upgrades the matched set, holds a duplicate for admin
        # review, or discards an upgrade attempt that turned out no better.
        result = await finish_arrival(
            live_set_id, upgrade_target_id=job.upgrade_target_set_id, trigger=trigger,
            **candidate,
        )
        finished = True
        # An upgrade repoints the job at the target; a discard detaches it.
        await session.refresh(job)
        await _set_status(session, job, "ready", progress_pct=100, message=result.message)
    except Exception as exc:
        # Surface the real exception in error_text (self-hosted, owner-only);
        # the full traceback still lands in server logs.
        logger.exception("rip job %s failed", job_id)
        if root is not None and not finished:
            try:
                await _discard_partial_rip(
                    session, job, root, created_live_set_id=created_live_set_id,
                )
            except Exception:
                logger.exception("rip job %s: failed to discard partial rip", job_id)
                await session.rollback()
                await session.refresh(job)  # rollback expired it; reload async
        try:
            job.error_text = _error_text(exc)
            # Once finish_arrival (or the early discard) has recorded the
            # outcome, a later failure must not add a "rip failed" event.
            if job.upgrade_target_set_id is not None and not finished:
                await _record_failed_upgrade_attempt(session, job)
            await _set_status(session, job, "failed", message="rip failed")
        except Exception:
            logger.exception("rip job %s: failed to record failure status", job_id)
    finally:
        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            logger.exception("rip job %s: tmp cleanup failed", job_id)


async def _record_failed_upgrade_attempt(session: AsyncSession, job: RipJob) -> None:
    """R31: a failed upgrade attempt is a rejected candidate for its target,
    so ``already_tried`` keeps later sweeps from re-picking it every run.
    Accepted (A3, R33a): a transient failure (network blip) burns that
    candidate for this set too. The caller commits (with the job's failed
    status)."""
    target = await session.get(LiveSet, job.upgrade_target_set_id)
    if target is None:
        return
    # The rip failed before it was measured: no tier or codec to record.
    session.add(build_upgrade_event(
        live_set_id=target.id, trigger=job.trigger or triggers.URL_RIP, outcome="rejected",
        reason=f"rip failed: {job.error_text or 'unknown error'}",
        **event_audio("from", target),
        to_source_type="url_rip", to_source_url=job.source_url,
        candidate_source_kind=job.source_platform,
        candidate_external_id=job.source_external_id,
    ))


async def _discard_unless_upgrade(
    live_set_id: uuid.UUID, *, target_id: uuid.UUID, trigger: str,
    candidate_source_kind: str | None, candidate_external_id: str | None,
) -> Decision | None:
    """Early upgrade check in its own session (the discard locks and may roll
    back). Returns the final decision when the rip should end here."""
    from setvault_core.services.upgrade_decision import discard_unless_upgrade

    async with session_factory()() as s:
        arrival = await s.get(LiveSet, live_set_id)
        if arrival is None:
            return None
        return await discard_unless_upgrade(
            s, arrival, target_id=target_id, trigger=trigger,
            candidate_source_kind=candidate_source_kind,
            candidate_external_id=candidate_external_id,
        )


def run_rip_job(*, rip_job_id: str) -> None:
    """RQ entry point. Re-resolves engine + session from env vars."""
    async def _main() -> None:
        if DATABASE_URL_ENV in os.environ:
            init_engine(os.environ[DATABASE_URL_ENV])
        async with session_factory()() as s:
            await _run_rip_job(s, uuid.UUID(rip_job_id))

    run_job(_main())
