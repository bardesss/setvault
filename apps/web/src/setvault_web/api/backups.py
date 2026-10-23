"""Admin -> Backups API (P2a A5): the scheduled database backups.

The files are written by the worker (``setvault_core.jobs.backup``) into the
backup dir (``effective_dir``, the same as the worker's). Only
names matching ``setvault-YYYYMMDD-HHMMSS.sql.gz`` are ever listed, served or
deleted, so a request can't reach any other file. The full DB + media export
stays at ``GET /api/admin/backup``.
"""
from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import FileResponse
from setvault_core.jobs.backup import (
    BACKUP_JOB_FUNC,
    BACKUP_JOB_TIMEOUT,
    BACKUP_NAME_RE,
    effective_dir,
    list_backups,
)
from setvault_core.models.identity import User
from setvault_core.models.system_config import SystemConfig
from setvault_core.services.audit import log as audit_log
from setvault_core.services.system_config import get_config
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_web.deps import current_user, db_session, require_admin

router = APIRouter(prefix="/api/admin/backups", tags=["admin"])

_DATA = Path("/data")


def dir_persistent(path: str | Path) -> bool:
    """True when the dir survives a container recreate: it's under the
    bundled ``/data`` volume, or it (or a parent) is a mount point. The
    filesystem root is always a mount and doesn't count. ``..`` is resolved
    first, so ``/data/../tmp`` is not under ``/data``."""
    p = Path(os.path.normpath(path))
    if p == _DATA or _DATA in p.parents:
        return True
    while p != p.parent:
        if os.path.ismount(p):
            return True
        p = p.parent
    return False


def _tz_name() -> str:
    return os.environ.get("TZ") or datetime.now().astimezone().tzname() or "UTC"


def _backup_file(name: str, cfg: SystemConfig) -> Path:
    """The named backup file, or 404 (bad name or missing)."""
    if not BACKUP_NAME_RE.fullmatch(name):
        raise HTTPException(status_code=404, detail="not found")
    path = effective_dir(cfg) / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="not found")
    return path


@router.get("")
async def list_backup_files(
    session: Annotated[AsyncSession, Depends(db_session)],
    _: Annotated[object, Depends(require_admin)],
):
    cfg = await get_config(session)
    directory = effective_dir(cfg)
    files = []
    for p in list_backups(directory):
        try:
            st = p.stat()
        except OSError:  # pruned meanwhile
            continue
        files.append({
            "name": p.name,
            "bytes": st.st_size,
            "created_at": datetime.fromtimestamp(st.st_mtime, UTC).isoformat(),
        })
    return {
        "dir": str(directory),
        "dir_persistent": dir_persistent(directory),
        "tz": _tz_name(),
        "files": files,
        "last": {
            "at": cfg.last_backup_at.isoformat() if cfg.last_backup_at else None,
            "status": cfg.last_backup_status,
            "error": cfg.last_backup_error,
            "bytes": cfg.last_backup_bytes,
        },
    }


@router.post("/run", status_code=202)
async def run_backup_now(
    session: Annotated[AsyncSession, Depends(db_session)],
    admin: Annotated[User, Depends(current_user)],
    _: Annotated[object, Depends(require_admin)],
):
    """Enqueue one backup now, even while scheduled backups are off."""
    from redis import Redis
    from rq import Queue

    redis = Redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
    rq_job = Queue("default", connection=redis).enqueue(
        BACKUP_JOB_FUNC, kwargs={"force": True}, job_timeout=BACKUP_JOB_TIMEOUT,
    )
    await audit_log(
        session, actor_user_id=admin.id, action="backup.run_requested",
        after={"job_id": rq_job.id},
    )
    await session.commit()
    return {"job_id": rq_job.id}


@router.get("/{name}")
async def download_backup_file(
    name: str,
    session: Annotated[AsyncSession, Depends(db_session)],
    _: Annotated[object, Depends(require_admin)],
):
    path = _backup_file(name, await get_config(session))
    return FileResponse(
        path,
        media_type="application/gzip",
        filename=name,
        # A full DB dump: no browser/SW/proxy may keep a copy.
        headers={"Cache-Control": "no-store"},
    )


@router.delete("/{name}", status_code=204)
async def delete_backup_file(
    name: str,
    session: Annotated[AsyncSession, Depends(db_session)],
    admin: Annotated[User, Depends(current_user)],
    _: Annotated[object, Depends(require_admin)],
) -> Response:
    path = _backup_file(name, await get_config(session))
    try:  # a concurrent prune may remove it meanwhile
        size = path.stat().st_size
        path.unlink()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="not found") from exc
    await audit_log(
        session, actor_user_id=admin.id, action="backup.deleted",
        target_type="backup", target_id=name, before={"name": name, "bytes": size},
    )
    await session.commit()
    return Response(status_code=204)
