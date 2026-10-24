"""Admin backup-download endpoint (§J2 minimum-viable).

GET /api/admin/backup streams a `tar` archive containing:
  - ``db.sql`` — a ``pg_dump --no-owner --no-privileges`` of the configured
    database, executed as a subprocess.
  - ``audio/<root_name>/...`` — every file under each MediaRoot's
    ``host_path``, preserving the on-disk layout.

The archive is streamed lazily — the response starts as soon as ``pg_dump``
begins producing output, so backups of large libraries don't have to buffer
the whole thing in memory. Failures (e.g. ``pg_dump`` not installed) abort
the stream and surface as a partial download — admin sees an incomplete
file size + a warning in the logs.

Scheduled (database-only) backups live in ``setvault_web.api.backups`` and
``setvault_core.jobs.backup``; this endpoint is the full DB + media export.
"""
from __future__ import annotations

import logging
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from setvault_core.models.catalog import MediaRoot
from setvault_core.services.pg_dump import stream_pg_dump as _stream_pg_dump
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_web.config import Settings, get_settings
from setvault_web.deps import db_session, require_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/backup", tags=["admin"])


def _stream_tar(database_url: str, roots: list[MediaRoot]):
    """Yield bytes of an uncompressed tar containing db.sql + each media root.

    Uncompressed tar lets us stream chunk-by-chunk without buffering the
    whole archive. Browsers happily download .tar; the admin can compress
    locally if disk space is a concern.

    The pg_dump output is spooled to a temp file (not accumulated in memory)
    so a large DB doesn't cause an admin-triggered OOM. The temp file gives
    us a known size for the tar header and constant memory usage; it's
    deleted as soon as the dump has been streamed into the archive.
    """
    import io
    import tempfile

    buffer = io.BytesIO()
    tar = tarfile.open(fileobj=buffer, mode="w|")

    # 1) db.sql — spool pg_dump to a temp file, then add it from that file so
    #    the dump never lives fully in memory.
    with tempfile.TemporaryFile() as dump_fp:
        for chunk in _stream_pg_dump(database_url):
            dump_fp.write(chunk)
        size = dump_fp.tell()
        dump_fp.seek(0)
        info = tarfile.TarInfo(name="db.sql")
        info.size = size
        info.mtime = int(datetime.now(UTC).timestamp())
        tar.addfile(info, dump_fp)
    buffer.seek(0)
    yield buffer.read()
    buffer.seek(0)
    buffer.truncate(0)

    # 2) each media root, walked recursively
    for root in roots:
        host = Path(root.host_path)
        if not host.is_dir():
            logger.warning("backup: media root %s missing on disk: %s", root.name, host)
            continue
        for file_path in host.rglob("*"):
            if not file_path.is_file():
                continue
            arc_name = f"audio/{root.name}/{file_path.relative_to(host)}"
            try:
                tar.add(str(file_path), arcname=arc_name, recursive=False)
            except OSError as exc:
                logger.warning("backup: skip %s (%s)", file_path, exc)
                continue
            buffer.seek(0)
            data = buffer.read()
            buffer.seek(0)
            buffer.truncate(0)
            if data:
                yield data

    tar.close()
    buffer.seek(0)
    final = buffer.read()
    if final:
        yield final


@router.get("")
async def download_backup(
    session: Annotated[AsyncSession, Depends(db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    _: Annotated[object, Depends(require_admin)],
):
    roots = list((await session.execute(
        select(MediaRoot).order_by(MediaRoot.created_at)
    )).scalars().all())

    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    filename = f"setvault-backup-{timestamp}.tar"

    # Sanitise the suggested filename — no path or quote characters.
    safe = "".join(c for c in filename if c.isalnum() or c in "-.")
    headers = {
        "Content-Disposition": f'attachment; filename="{safe}"',
        # Contains the full DB dump; no browser/SW/proxy may keep a copy.
        "Cache-Control": "no-store",
    }
    return StreamingResponse(
        _stream_tar(settings.database_url, roots),
        media_type="application/x-tar",
        headers=headers,
    )
