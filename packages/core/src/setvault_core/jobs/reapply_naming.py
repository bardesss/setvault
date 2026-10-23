"""Worker job for reapplying a MediaRoot's naming_template over its existing
LiveSets (admin-triggered from `POST /api/admin/media-roots/{id}/reapply-template`).

Each non-deleted LiveSet on the root goes through
:func:`setvault_core.jobs.apply_naming.apply_naming_to_set`, which places the
file under its new name, commits ``audio_path`` and only then unlinks the old
name (when no set references it). See that module for the file-safety rules.

Per-set failures are logged and counted but do not abort the rest of the job.
The summary is written to a ``media_root.naming_reapplied`` audit event.
"""
from __future__ import annotations

import logging
import os
import uuid

from sqlalchemy import select

from setvault_core.db import init_engine, run_job, session_factory
from setvault_core.jobs.apply_naming import apply_naming_to_set
from setvault_core.models.catalog import LiveSet, MediaRoot
from setvault_core.services.audit import log as audit_log

logger = logging.getLogger(__name__)


async def reapply_naming_template(media_root_id: str) -> dict:
    """Walk every LiveSet on the root and apply its naming_template.

    Returns a summary dict (``{"renamed": N, "unchanged": N, "skipped": N,
    "errors": N}``) so the admin UI can show the result. ``skipped`` counts
    sets whose source file is missing or whose name renders empty. The dict
    is also written to an audit event keyed on the media root.
    """
    if "DATABASE_URL" in os.environ:
        init_engine(os.environ["DATABASE_URL"])

    summary = {"renamed": 0, "unchanged": 0, "skipped": 0, "errors": 0}
    root_uuid = uuid.UUID(media_root_id)

    async with session_factory()() as s:
        root = await s.get(MediaRoot, root_uuid)
        if root is None or not root.naming_template:
            return summary

        set_ids = (await s.execute(
            select(LiveSet.id)
            .where(LiveSet.media_root_id == root_uuid)
            .where(LiveSet.deleted_at.is_(None))
            .order_by(LiveSet.created_at, LiveSet.id)
        )).scalars().all()

        for set_id in set_ids:
            try:
                # Fresh copies each time: a failed set's rollback expires the
                # session's objects.
                root = await s.get(MediaRoot, root_uuid, populate_existing=True)
                live = await s.get(LiveSet, set_id, populate_existing=True)
                if root is None or live is None or live.deleted_at is not None:
                    continue
                outcome = await apply_naming_to_set(s, live, root)
                summary[outcome] += 1
            except Exception:
                summary["errors"] += 1
                logger.exception("reapply: failed for %s", set_id)
                await s.rollback()

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