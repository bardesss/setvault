"""Worker job for reapplying a MediaRoot's naming_template over its existing
LiveSets (admin-triggered from `POST /api/admin/media-roots/{id}/reapply-template`).

For each LiveSet under the root: compute the new relative path via
``render_filename``; if it differs from the current ``audio_path``, hardlink
(or copy) the file at the new location, update the DB, then unlink the old
name. The placement helper handles same-fs vs cross-fs differences.

Per-set failures are logged + recorded in an audit event but do not abort
the rest of the job. The original file is *only* unlinked after the DB
update commits successfully — a crash mid-job leaves both old and new names
alive (hardlink == cheap, copy == known waste; admin can re-run).
"""
from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path

from sqlalchemy import select

from setvault_core.db import init_engine, run_job, session_factory
from setvault_core.models.catalog import LiveSet, MediaRoot
from setvault_core.services.audit import log as audit_log
from setvault_core.services.naming import render_filename
from setvault_core.services.storage import place_audio_file

logger = logging.getLogger(__name__)


async def reapply_naming_template(media_root_id: str) -> dict:
    """Walk every LiveSet on the root and apply its naming_template.

    Returns a summary dict (``{"renamed": N, "skipped": N, "errors": N}``) so
    the admin UI can show the result. The dict is also written to an audit
    event keyed on the media root.
    """
    if "DATABASE_URL" in os.environ:
        init_engine(os.environ["DATABASE_URL"])

    summary = {"renamed": 0, "skipped": 0, "errors": 0}
    root_uuid = uuid.UUID(media_root_id)

    async with session_factory()() as s:
        root = await s.get(MediaRoot, root_uuid)
        if root is None or not root.naming_template:
            return summary

        live_rows = (await s.execute(
            select(LiveSet)
            .where(LiveSet.media_root_id == root_uuid)
            .where(LiveSet.deleted_at.is_(None))
        )).scalars().all()

        host_root = Path(root.host_path)
        template = root.naming_template

        for live in live_rows:
            try:
                ext = Path(live.audio_path).suffix
                new_relpath = render_filename(template, live, ext=ext)
                if not new_relpath or new_relpath == live.audio_path:
                    summary["skipped"] += 1
                    continue
                old_abs = host_root / live.audio_path
                new_abs = host_root / new_relpath
                if not old_abs.exists():
                    summary["errors"] += 1
                    logger.warning("reapply: source missing for %s", live.id)
                    continue
                place_audio_file(old_abs, new_abs)
                live.audio_path = new_relpath
                await s.commit()
                # Only unlink old AFTER the DB commit succeeded
                try:
                    if old_abs.exists() and old_abs.resolve() != new_abs.resolve():
                        old_abs.unlink()
                except OSError as exc:
                    logger.warning(
                        "reapply: post-commit unlink failed for %s: %s",
                        old_abs, exc,
                    )
                summary["renamed"] += 1
            except Exception:
                summary["errors"] += 1
                logger.exception("reapply: failed for %s", live.id)

        await audit_log(
            s,
            actor_user_id=None,
            actor_kind="system",
            action="media_root.naming_reapplied",
            target_type="MediaRoot",
            target_id=str(root_uuid),
            after=summary,
        )
        await s.commit()
    return summary


def run_reapply_naming_template(media_root_id: str) -> dict:
    """RQ entry point."""
    return run_job(reapply_naming_template(media_root_id))
