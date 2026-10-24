"""Scheduled database backups (P2a A5).

An hourly tick (``run_backup_tick``, registered in the worker's
``_SCHEDULE``) runs the backup once a day, at the first tick at or after
``SystemConfig.backup_time`` in the container's time zone (``TZ``). A worker
that was down at that time catches up on its next tick the same day.

A backup is the database only: ``pg_dump`` (the same flags as the on-demand
download) gzipped to ``setvault-YYYYMMDD-HHMMSS.sql.gz`` in the backup dir.
Media and ``.secrets`` are deliberately left out. The dump is written to a
``.tmp`` file and renamed when complete, then the oldest backups beyond
``backup_keep`` are pruned (only files matching the name pattern).

The outcome lands in ``SystemConfig.last_backup_*``; a failure also sends
the admins a ``maintenance`` notification. The worker records each run in
Jobs.
"""
from __future__ import annotations

import gzip
import logging
import os
import re
import shutil
from datetime import UTC, datetime, time
from pathlib import Path

from setvault_core.db import init_engine, run_job, session_factory
from setvault_core.models.system_config import SystemConfig
from setvault_core.services import pg_dump
from setvault_core.services.notifications import notify_backup_failed
from setvault_core.services.system_config import get_config

logger = logging.getLogger(__name__)

DEFAULT_BACKUP_DIR = "/srv/backups"
BACKUP_NAME_RE = re.compile(r"^setvault-\d{8}-\d{6}\.sql\.gz$")
# "Back up now" (POST /api/admin/backups/run) enqueues this with force=True.
BACKUP_JOB_FUNC = "setvault_core.jobs.backup.run_backup"
BACKUP_JOB_TIMEOUT = "2h"


def effective_dir(cfg: SystemConfig) -> Path:
    """The configured backup dir, else ``SETVAULT_BACKUP_PATH``, else
    ``/srv/backups``."""
    return Path(
        cfg.backup_dir or os.environ.get("SETVAULT_BACKUP_PATH") or DEFAULT_BACKUP_DIR
    )


def is_due(
    now_local: datetime, backup_time: str, last_backup_at_local: datetime | None,
) -> bool:
    """True once ``now_local`` is at or past ``backup_time`` ("HH:MM") and no
    successful backup has run yet on ``now_local``'s date.

    ``last_backup_at_local`` is the last *successful* run, in the same zone
    as ``now_local``.
    """
    hh, mm = (int(part) for part in backup_time.split(":"))
    if now_local.time() < time(hh, mm):
        return False
    return last_backup_at_local is None or last_backup_at_local.date() != now_local.date()


def ensure_backup_dir(directory: str | Path) -> Path:
    """Create the backup dir owner-only (0700) when it's missing. An existing
    dir keeps its mode (it may be a user-chosen share); the dumps themselves
    are written 0600, since they hold password hashes and tokens."""
    directory = Path(directory)
    try:
        directory.mkdir(mode=0o700, parents=True)
    except FileExistsError:
        if not directory.is_dir():
            raise
        return directory
    if os.name == "posix":
        os.chmod(directory, 0o700)  # mkdir's mode is subject to the umask
    return directory


def _mtime(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except OSError:  # removed meanwhile
        return 0.0


def scan_backups(directory: Path) -> tuple[list[Path], str | None]:
    """Backup files in ``directory``, newest first by mtime (not by name: a
    TZ change shifts the timestamps in names), plus why the dir couldn't be
    read (``None`` when it could, or doesn't exist yet)."""
    try:
        entries = list(directory.iterdir())
    except FileNotFoundError:
        return [], None
    except OSError as exc:  # e.g. not readable by this uid
        return [], exc.strerror or str(exc)
    files = [p for p in entries if BACKUP_NAME_RE.fullmatch(p.name) and p.is_file()]
    return sorted(files, key=lambda p: (_mtime(p), p.name), reverse=True), None


def list_backups(directory: Path) -> list[Path]:
    """``scan_backups`` without the error: an unreadable dir lists empty."""
    return scan_backups(directory)[0]


def _human(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


_NEW_FILE_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)


def _dump_to(fd: int, database_url: str) -> None:
    """Stream ``pg_dump`` through gzip into the open file ``fd`` (closed after)."""
    with os.fdopen(fd, "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb") as out:
        for chunk in pg_dump.stream_pg_dump(database_url, check=True):
            out.write(chunk)


def _publish(tmp: Path, final: Path) -> None:
    """Give the finished ``tmp`` its final name, never replacing a file."""
    try:
        os.link(tmp, final)
    except FileExistsError:
        raise RuntimeError(f"backup file {final.name} already exists") from None
    except OSError:
        # No hard links on this filesystem: check, then rename.
        if final.exists():
            raise RuntimeError(f"backup file {final.name} already exists") from None
        os.replace(tmp, final)
        return
    tmp.unlink()


def _prune(directory: Path, keep: int) -> list[str]:
    pruned: list[str] = []
    for old in list_backups(directory)[keep:]:
        try:
            old.unlink()
        except OSError as exc:
            logger.warning("backup: could not prune %s: %s", old, exc)
            continue
        pruned.append(old.name)
    return pruned


def _write(directory: Path, last_bytes: int | None, keep: int, database_url: str) -> dict:
    """Space check, dump, rename, prune. Raises on failure."""
    if not database_url:
        raise RuntimeError("DATABASE_URL is not set")
    ensure_backup_dir(directory)
    free = shutil.disk_usage(directory).free
    if last_bytes and last_bytes * 2 > free:
        raise RuntimeError(
            f"not enough free space (need ~{_human(last_bytes * 2)}, have {_human(free)})"
        )
    name = f"setvault-{datetime.now().astimezone():%Y%m%d-%H%M%S}.sql.gz"
    final = directory / name
    if final.exists():
        raise RuntimeError(f"backup file {name} already exists")
    tmp = directory / f"{name}.tmp"
    # O_EXCL: never write into another run's tmp; 0600: owner-only from the start.
    try:
        fd = os.open(tmp, _NEW_FILE_FLAGS, 0o600)
    except FileExistsError:
        raise RuntimeError(f"backup file {tmp.name} already exists") from None
    try:
        _dump_to(fd, database_url)
        _publish(tmp, final)
    except BaseException:
        tmp.unlink(missing_ok=True)  # ours: created above
        raise
    size = final.stat().st_size
    return {"file": name, "bytes": size, "pruned": _prune(directory, keep)}


async def perform_backup(force: bool = False) -> dict:
    """Run one backup now. Skipped while backups are disabled unless
    ``force`` (the admin's "Back up now").

    Returns ``{"status", "file", "bytes", "pruned"}`` (plus ``"error"`` when
    it failed).
    """
    database_url = os.environ.get("DATABASE_URL", "")
    if database_url:
        init_engine(database_url)
    # Read what's needed and close the session before the (possibly long) dump.
    async with session_factory()() as s:
        cfg = await get_config(s)
        enabled = cfg.backup_enabled
        directory = effective_dir(cfg)
        keep = cfg.backup_keep
        last_bytes = cfg.last_backup_bytes
    if not enabled and not force:
        return {"status": "skipped", "file": None, "bytes": None, "pruned": []}

    try:
        result = _write(directory, last_bytes, keep, database_url)
    except Exception as exc:  # any failure is recorded, never raised
        error = str(exc) or type(exc).__name__
        logger.exception("backup: failed: %s", error)
        async with session_factory()() as s:
            cfg = await get_config(s)
            # The hourly retry keeps failing all day: notify on the day's
            # first failure only (local day, like the schedule).
            now_local = datetime.now().astimezone()
            failed_today = (
                cfg.last_backup_status == "failed"
                and cfg.last_backup_at is not None
                and cfg.last_backup_at.astimezone(now_local.tzinfo).date() == now_local.date()
            )
            cfg.last_backup_at = now_local.astimezone(UTC)
            cfg.last_backup_status = "failed"
            cfg.last_backup_error = error
            if not failed_today:
                await notify_backup_failed(s, error)
            await s.commit()
        return {"status": "failed", "file": None, "bytes": None, "pruned": [], "error": error}

    async with session_factory()() as s:
        cfg = await get_config(s)
        cfg.last_backup_at = datetime.now(UTC)
        cfg.last_backup_status = "ok"
        cfg.last_backup_error = None
        cfg.last_backup_bytes = result["bytes"]
        await s.commit()
    logger.info("backup: wrote %s (%s), pruned %d",
                result["file"], _human(result["bytes"]), len(result["pruned"]))
    return {"status": "ok", **result}


async def backup_tick() -> dict | None:
    """Run the day's backup when it is enabled and due; else ``None``."""
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        init_engine(database_url)
    async with session_factory()() as s:
        cfg = await get_config(s)
        enabled = cfg.backup_enabled
        backup_time = cfg.backup_time
        last_ok = cfg.last_backup_at if cfg.last_backup_status == "ok" else None
    now_local = datetime.now().astimezone()
    last_ok_local = last_ok.astimezone(now_local.tzinfo) if last_ok else None
    if not enabled or not is_due(now_local, backup_time, last_ok_local):
        return None
    return await perform_backup()


def run_backup(force: bool = False) -> dict:
    """RQ entry point for one backup ("Back up now" passes ``force=True``)."""
    return run_job(perform_backup(force))


def run_backup_tick() -> dict | None:
    """RQ entry point for the hourly tick."""
    return run_job(backup_tick())
