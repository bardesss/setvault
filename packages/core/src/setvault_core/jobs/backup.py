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


def list_backups(directory: Path) -> list[Path]:
    """Backup files in ``directory``, newest first (the name sorts by time)."""
    try:
        entries = list(directory.iterdir())
    except FileNotFoundError:
        return []
    files = [p for p in entries if BACKUP_NAME_RE.fullmatch(p.name) and p.is_file()]
    return sorted(files, key=lambda p: p.name, reverse=True)


def _human(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def _dump_to(path: Path, database_url: str) -> int:
    """Stream ``pg_dump`` through gzip into ``path``; returns the file size."""
    with gzip.open(path, "wb") as out:
        for chunk in pg_dump.stream_pg_dump(database_url, check=True):
            out.write(chunk)
    return path.stat().st_size


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
    directory.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(directory).free
    if last_bytes and last_bytes * 2 > free:
        raise RuntimeError(
            f"not enough free space (need ~{_human(last_bytes * 2)}, have {_human(free)})"
        )
    name = f"setvault-{datetime.now().astimezone():%Y%m%d-%H%M%S}.sql.gz"
    final = directory / name
    tmp = directory / f"{name}.tmp"
    try:
        size = _dump_to(tmp, database_url)
        os.replace(tmp, final)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
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
            cfg.last_backup_at = datetime.now(UTC)
            cfg.last_backup_status = "failed"
            cfg.last_backup_error = error
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
