"""Watch-folder ingest worker job.

Triggered by the filesystem watcher (`services/watcher.py`) for each detected
audio file. For each file:

1. Verify it's still on disk and isn't an in-flight ``.tmp``.
2. ffprobe for duration + audio-stream presence.
3. Attempt to parse a date / artist / title from the filename.
4. **If the filename parses cleanly**: create a draft ``LiveSet`` pointing at
   the file (hardlinked or copied into the target root's ``originals/``),
   then chain into the existing pipeline. Fingerprint dedup happens inside
   the pipeline; if it detects a duplicate the draft just inherits
   ``duplicate_of`` and the admin can resolve later.
5. **Otherwise**: write an ``UnmatchedFile`` row with the probe payload so
   the admin sees it in the Unmatched inbox.

The job never deletes or moves the source file unless we successfully placed
it (hardlink semantics keep both names alive on success); failure leaves the
source where the watcher found it so a retry sees the same state.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import uuid
from datetime import UTC, datetime
from datetime import date as date_cls
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_core.db import init_engine, run_job, session_factory
from setvault_core.models.catalog import LiveSet, MediaRoot
from setvault_core.models.identity import User
from setvault_core.models.watch_folder import UnmatchedFile, WatchFolder
from setvault_core.services.storage import place_audio_file

logger = logging.getLogger(__name__)


# Filename patterns, tried in order. First match wins.
#
# Group names that we read:
#   year, month, day  -> parsed into a date.date()
#   artist            -> set artist hint (free text; resolved later)
#   title             -> set title
# RUF001 ambiguous-character warnings on the en-dash are intentional: the
# regex deliberately matches both ASCII hyphen-minus AND Unicode en-dash so
# files named with U+2013 (common from macOS auto-rename) still parse.
_FILENAME_PATTERNS: tuple[re.Pattern[str], ...] = (
    # 2026-01-15 - Artist Name - Title Of Set.opus
    re.compile(
        r"^(?P<year>\d{4})[-_.](?P<month>\d{2})[-_.](?P<day>\d{2})\s*[-–]\s*"  # noqa: RUF001
        r"(?P<artist>.+?)\s*[-–]\s*(?P<title>.+?)$",  # noqa: RUF001
        re.IGNORECASE,
    ),
    # 2026.01.15 Artist - Title.opus  (no dash before artist)
    re.compile(
        r"^(?P<year>\d{4})[-_.](?P<month>\d{2})[-_.](?P<day>\d{2})\s+"
        r"(?P<artist>.+?)\s*[-–]\s*(?P<title>.+?)$",  # noqa: RUF001
        re.IGNORECASE,
    ),
    # Artist - Title.opus  (no date)
    re.compile(
        r"^(?P<artist>.+?)\s*[-–]\s*(?P<title>.+?)$",  # noqa: RUF001
    ),
)


def _parse_filename(stem: str) -> dict | None:
    """Return ``{date?, artist, title}`` if any pattern matches, else None.

    ``stem`` is the filename without its extension. Leading / trailing
    whitespace is stripped before matching.
    """
    s = stem.strip()
    for pattern in _FILENAME_PATTERNS:
        m = pattern.match(s)
        if not m:
            continue
        groups = m.groupdict()
        result: dict[str, object] = {
            "artist": groups["artist"].strip(),
            "title": groups["title"].strip(),
        }
        if all(groups.get(k) for k in ("year", "month", "day")):
            try:
                result["date"] = date_cls(
                    int(groups["year"]), int(groups["month"]), int(groups["day"]),
                )
            except ValueError:
                # Bad date (e.g. 2026-13-99); fall through and skip date field
                pass
        if result["artist"] and result["title"]:
            return result
    return None


def _probe_audio(path: Path) -> dict | None:
    """Run ffprobe over the file. Returns the parsed JSON dict, or None on
    failure (corrupt file, not audio, ffprobe missing, etc.)."""
    try:
        # S603/S607 noqa: ffprobe is a system binary expected on PATH; same
        # pattern as fingerprint.py / probe.py / normalize.py for fpcalc and
        # ffmpeg. Arguments are not user-controlled — file path is from the
        # watcher's filesystem event.
        out = subprocess.run(  # noqa: S603
            [  # noqa: S607
                "ffprobe", "-v", "error", "-show_format", "-show_streams",
                "-of", "json", str(path),
            ],
            check=True, capture_output=True, text=True, timeout=30,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return None
    try:
        data = json.loads(out.stdout)
    except json.JSONDecodeError:
        return None
    streams = data.get("streams", []) or []
    if not any(s.get("codec_type") == "audio" for s in streams):
        return None
    return data


def _slugify(text: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9-]+", "-", text.lower()).strip("-")
    return s[:60] or "untitled"


async def _record_unmatched(
    session: AsyncSession,
    *,
    watch_folder_id: uuid.UUID,
    file_path: str,
    audio_info: dict | None,
    error_text: str | None = None,
) -> None:
    row = UnmatchedFile(
        watch_folder_id=watch_folder_id,
        file_path=file_path,
        audio_info=audio_info or {},
        resolution="pending",
        error_text=error_text,
    )
    session.add(row)
    await session.commit()


async def _ingest_actor(session: AsyncSession, watch_folder: WatchFolder) -> User:
    """The user a watch-folder ingest is attributed to: the admin who created
    the folder while they're still an active admin, otherwise the first
    active admin (folders created before ``created_by`` existed, or whose
    creator was removed, disabled or demoted)."""
    if watch_folder.created_by is not None:
        creator = await session.get(User, watch_folder.created_by)
        if creator is not None and creator.role == "admin" and creator.disabled_at is None:
            return creator
    admin = (await session.execute(
        select(User).where(User.role == "admin", User.disabled_at.is_(None))
        .order_by(User.created_at).limit(1),
    )).scalar_one_or_none()
    if admin is None:
        raise RuntimeError("no admin user to attribute the watch-folder ingest to")
    return admin


async def _make_draft_set(
    session: AsyncSession,
    *,
    watch_folder: WatchFolder,
    parsed: dict,
    source_path: Path,
    audio_info: dict,
) -> LiveSet:
    """Create a LiveSet draft, hardlink/copy the audio into originals/, return the row."""
    root = await session.get(MediaRoot, watch_folder.target_media_root_id)
    if root is None:
        raise RuntimeError("watch folder's target MediaRoot is gone")

    uploader = await _ingest_actor(session, watch_folder)

    new_set_id = uuid.uuid4()
    audio_relpath = f"originals/{new_set_id}/{source_path.name}"
    dst = Path(root.host_path) / audio_relpath
    placement_mode = place_audio_file(source_path, dst)

    title = parsed.get("title") or source_path.stem
    slug = _slugify(title) + "-" + new_set_id.hex[:6]
    duration_seconds: int | None = None
    fmt_block = audio_info.get("format", {}) or {}
    if "duration" in fmt_block:
        try:
            duration_seconds = int(float(fmt_block["duration"]))
        except (TypeError, ValueError):
            duration_seconds = None

    parsed_date = parsed.get("date") if isinstance(parsed.get("date"), date_cls) else None

    live = LiveSet(
        id=new_set_id,
        slug=slug,
        title=title,
        date=parsed_date,
        duration_seconds=duration_seconds,
        source_type="watch_folder",
        source_url=str(source_path),
        media_root_id=root.id,
        audio_path=audio_relpath,
        status="draft",
        uploaded_by=uploader.id,
    )
    session.add(live)
    await session.commit()
    logger.info(
        "watch_folder %s placed %s -> %s (%s) as set %s",
        watch_folder.id, source_path, dst, placement_mode, new_set_id,
    )
    return live


async def _trigger_pipeline(live_set_id: uuid.UUID) -> None:
    """Kick the existing transcode/normalize/waveform/ready chain via RQ.

    Decoupled into its own enqueue so the unit tests can monkeypatch this
    without standing up Redis.
    """
    from redis import Redis
    from rq import Queue

    from setvault_core.jobs.pipeline import PIPELINE_JOB_TIMEOUT

    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    Queue("default", connection=Redis.from_url(redis_url)).enqueue(
        "setvault_core.jobs.pipeline.run_pipeline",
        str(live_set_id),
        job_timeout=PIPELINE_JOB_TIMEOUT,
    )


async def _run_one(
    session: AsyncSession,
    *,
    watch_folder_id: uuid.UUID,
    file_path: str,
) -> None:
    wf = await session.get(WatchFolder, watch_folder_id)
    if wf is None:
        logger.warning("watch_folder_ingest: WatchFolder %s gone", watch_folder_id)
        return

    src = Path(file_path)
    # ASYNC240 noqa: a single stat() on the source file is bounded; same
    # precedent as apps/web uploads.py and url_rip_job.py _download fallback.
    if not src.exists():  # noqa: ASYNC240
        logger.info("watch_folder_ingest: source vanished before pickup: %s", file_path)
        return

    audio_info = _probe_audio(src) or {}
    if not audio_info:
        await _record_unmatched(
            session,
            watch_folder_id=wf.id,
            file_path=file_path,
            audio_info=None,
            error_text="ffprobe failed or no audio streams",
        )
        return

    parsed = _parse_filename(src.stem)
    if parsed is None:
        await _record_unmatched(
            session,
            watch_folder_id=wf.id,
            file_path=file_path,
            audio_info=audio_info,
            error_text="filename does not match any known pattern",
        )
        return

    live = await _make_draft_set(
        session,
        watch_folder=wf,
        parsed=parsed,
        source_path=src,
        audio_info=audio_info,
    )

    # Update WatchFolder.last_event_at so admins see the watcher is active.
    wf.last_event_at = datetime.now(UTC)
    await session.commit()

    await _trigger_pipeline(live.id)


def run_watch_folder_ingest(
    *, watch_folder_id: str, file_path: str,
) -> None:
    """RQ entry point. ``watch_folder_id`` is a string-UUID."""
    async def _main() -> None:
        if "DATABASE_URL" in os.environ:
            init_engine(os.environ["DATABASE_URL"])
        async with session_factory()() as s:
            await _run_one(
                s,
                watch_folder_id=uuid.UUID(watch_folder_id),
                file_path=file_path,
            )

    run_job(_main())
