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
import re
import shutil
import subprocess
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_core.db import init_engine, run_job, session_factory
from setvault_core.models.catalog import LiveSet, MediaRoot
from setvault_core.models.url_rip import RipJob

logger = logging.getLogger(__name__)

DATABASE_URL_ENV = "DATABASE_URL"


_ERROR_TEXT_MAX = 500

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
        "format": "bestaudio/best",
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
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
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


def _slugify(text: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9-]+", "-", text.lower()).strip("-")
    return s[:60] or "untitled"


async def _create_draft_live_set(
    session: AsyncSession, job: RipJob, *, root: MediaRoot, audio_relpath: str,
) -> LiveSet:
    """Materialise a draft LiveSet for this rip pointing at the downloaded file."""
    meta = job.probed_metadata or {}
    title = meta.get("title") or "(untitled)"
    slug = _slugify(title) + "-" + uuid.uuid4().hex[:6]
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


async def _run_rip_job(session: AsyncSession, job_id: uuid.UUID) -> None:
    """The pipeline itself. Separated from the RQ entry point for testing."""
    job = await session.get(RipJob, job_id)
    if job is None:
        logger.warning("rip job %s not found", job_id)
        return

    tmp_dir = Path(tempfile.mkdtemp(prefix=f"setvault-rip-{job_id}-"))
    try:
        root = (await session.execute(
            select(MediaRoot).where(MediaRoot.default_for_ingest.is_(True))
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
        live_set_id = str(live.id)

        # The downstream stages each open their own session via session_factory()
        # and emit ProgressEvents tied to the LiveSet. We just update the RipJob
        # marker between phases so the Jobs drawer reflects what's running.
        from setvault_core.jobs.fingerprint import fingerprint_audio
        from setvault_core.jobs.normalize import normalize_audio
        from setvault_core.jobs.probe import probe_audio
        from setvault_core.jobs.ready import mark_ready
        from setvault_core.jobs.transcode import transcode_audio
        from setvault_core.jobs.waveform import generate_waveform

        await _set_status(session, job, "probing", progress_pct=30,
                          message="probing audio")
        await probe_audio(live_set_id)

        # Same chromaprint dedup as uploads and watch-folder ingest: flags
        # duplicate_of (or restores a recycled original) and records the
        # SetFingerprint that later rips/uploads and upgrade matching check.
        await _set_status(session, job, "probing", progress_pct=38,
                          message="fingerprinting")
        await fingerprint_audio(live_set_id)

        await _set_status(session, job, "transcoding", progress_pct=45,
                          message="encoding Opus")
        await transcode_audio(live_set_id)

        await _set_status(session, job, "normalizing", progress_pct=65,
                          message="EBU R128 scan")
        await normalize_audio(live_set_id)

        await _set_status(session, job, "waveform", progress_pct=85,
                          message="rendering waveform")
        await generate_waveform(live_set_id)

        # mark_ready holds fingerprint duplicates as drafts for admin review.
        published = await mark_ready(live_set_id) is not False
        await _set_status(session, job, "ready", progress_pct=100,
                          message="published" if published
                          else "held for review: duplicate")
    except Exception as exc:
        # Surface the real exception in error_text (self-hosted, owner-only);
        # the full traceback still lands in server logs.
        logger.exception("rip job %s failed", job_id)
        try:
            job.error_text = _error_text(exc)
            await _set_status(session, job, "failed", message="rip failed")
        except Exception:
            logger.exception("rip job %s: failed to record failure status", job_id)
    finally:
        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            logger.exception("rip job %s: tmp cleanup failed", job_id)


def run_rip_job(*, rip_job_id: str) -> None:
    """RQ entry point. Re-resolves engine + session from env vars."""
    async def _main() -> None:
        if DATABASE_URL_ENV in os.environ:
            init_engine(os.environ[DATABASE_URL_ENV])
        async with session_factory()() as s:
            await _run_rip_job(s, uuid.UUID(rip_job_id))

    run_job(_main())
