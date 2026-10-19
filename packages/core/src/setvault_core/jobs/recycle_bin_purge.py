"""Scheduled hourly job that purges soft-deleted LiveSets whose grace window
has expired (§J8).

Selection rule: ``deleted_at IS NOT NULL AND purge_after_at < now()``.

For each match:
  1. Best-effort remove the on-disk audio + streaming + waveform files (the
     containing per-set directory under ``originals/<set_id>`` is also
     removed when it becomes empty). A file another LiveSet still references
     is kept (``services.storage.path_in_use``).
  2. Delete the LiveSet row. SetFingerprint, TracklistEntry, Comment,
     Bookmark, etc. cascade automatically per their FK ondelete clauses.
  3. Emit a ``set.purged`` audit event so admin retains visibility.

Filesystem errors per-set DO NOT abort the run — they're logged and counted
in the returned summary so the next pass picks the row up again.
"""
from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from setvault_core.db import init_engine, run_job, session_factory
from setvault_core.models.catalog import LiveSet, MediaRoot
from setvault_core.services.audit import log as audit_log
from setvault_core.services.storage import path_in_use

logger = logging.getLogger(__name__)


def _try_delete(path: Path) -> bool:
    """Best-effort file delete. Returns True if the file was removed or
    didn't exist; False on permission/other OS errors."""
    try:
        if path.exists():
            path.unlink()
        return True
    except OSError as exc:
        logger.warning("purge: failed to unlink %s: %s", path, exc)
        return False


def _try_rmdir(path: Path) -> None:
    """Best-effort empty-dir removal. Silently ignores non-empty / missing."""
    try:
        path.rmdir()
    except OSError:
        pass


def _rmdir_empty_parents(path: Path, stop: Path) -> None:
    """Remove ``path``'s now-empty parent dirs strictly below ``stop`` (the
    ``originals/`` dir, which itself stays). Paths outside it are left be."""
    parent = path.parent
    if not parent.is_relative_to(stop):
        return
    while parent != stop:
        try:
            parent.rmdir()
        except OSError:
            return  # not empty (or gone / not permitted): stop here
        parent = parent.parent


async def purge_recycle_bin() -> dict:
    """Walk eligible sets and delete them. Returns ``{"purged": N, "errors": N}``."""
    if "DATABASE_URL" in os.environ:
        init_engine(os.environ["DATABASE_URL"])

    summary = {"purged": 0, "errors": 0}
    now = datetime.now(UTC)

    async with session_factory()() as s:
        rows = (await s.execute(
            select(LiveSet).where(
                LiveSet.deleted_at.is_not(None),
                LiveSet.purge_after_at.is_not(None),
                LiveSet.purge_after_at < now,
            )
        )).scalars().all()

        for live in rows:
            live_set_id = live.id
            try:
                root = await s.get(MediaRoot, live.media_root_id)
                host_root = Path(root.host_path) if root else None

                paths_to_delete: list[Path] = []
                if host_root is not None:
                    for rel in (live.audio_path, live.streaming_path,
                                live.waveform_path, live.thumb_path):
                        if not rel:
                            continue
                        # After a quality upgrade a live set can name the
                        # same file; never delete it from under that set.
                        if await path_in_use(s, live.media_root_id, rel,
                                             exclude_live_set_id=live_set_id):
                            logger.info("purge: keeping %s, another set uses it", rel)
                            continue
                        paths_to_delete.append(host_root / rel)

                ok = all(_try_delete(p) for p in paths_to_delete)
                if not ok:
                    summary["errors"] += 1
                    continue

                # Tidy up empty per-set originals/<set_id>/ dirs left behind:
                # this set's own, and the parents of every file deleted (after
                # an upgrade swap the recycled copy's audio lives under the
                # target's id).
                if host_root is not None:
                    _try_rmdir(host_root / "originals" / str(live_set_id))
                    for p in paths_to_delete:
                        _rmdir_empty_parents(p, host_root / "originals")

                await audit_log(
                    s,
                    actor_user_id=live.uploaded_by,
                    actor_kind="system",
                    action="set.purged",
                    target_type="LiveSet",
                    target_id=str(live_set_id),
                    before={
                        "slug": live.slug,
                        "title": live.title,
                        "deleted_at": live.deleted_at.isoformat() if live.deleted_at else None,
                    },
                )
                await s.delete(live)
                await s.commit()
                summary["purged"] += 1
            except Exception:
                summary["errors"] += 1
                logger.exception("purge: failed for set %s", live_set_id)
                await s.rollback()

    return summary


def run_purge_recycle_bin() -> dict:
    """RQ entry point."""
    return run_job(purge_recycle_bin())
