"""Apply a media root's naming template to one set's audio file (P2a A4).

``apply_naming_to_set`` is the one place a set's audio file is renamed to
its template path. It is used by the per-set job (enqueued at publish, after
a quality upgrade and after metadata edits) and by the admin "Re-apply
template" job (``reapply_naming``). Only ``audio_path`` moves; the stream,
waveform and thumb files are internal and stay put.

File safety, in order:

1. The new name is chosen so it never replaces anything: a name that exists
   on disk or that another set on the root references gets ` (2)`, ` (3)` ...
   before the extension.
2. ``place_audio_file`` adds the new name (hardlink, or copy + atomic rename
   across filesystems). The old name stays.
3. ``audio_path`` is committed.
4. Only then is the old name unlinked, and only when no set references it.

A crash or failed commit between 2 and 3 leaves both names on disk and the
row on the old one; nothing is lost and re-running is safe.
"""
from __future__ import annotations

import itertools
import logging
import os
import uuid
from pathlib import Path, PurePosixPath
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_core.db import init_engine, run_job, session_factory
from setvault_core.models.catalog import LiveSet, MediaRoot
from setvault_core.services.naming import render_filename
from setvault_core.services.storage import path_in_use, place_audio_file, resolve_set_path

logger = logging.getLogger(__name__)

NamingOutcome = Literal["unchanged", "renamed", "skipped"]

# Collision suffixes tried before giving up: (2) ... (_MAX_SUFFIX).
_MAX_SUFFIX = 1000


def _path(root: MediaRoot, rel: str) -> Path:
    """`rel` under the root, unresolved (a symlink is handled as itself,
    never as the file it points at). Raises ValueError if it escapes the root."""
    resolve_set_path(root.host_path, rel)
    return Path(root.host_path) / rel


def _with_suffix(rel: str, ext: str, n: int) -> str:
    """``a/b.flac`` -> ``a/b (n).flac``."""
    if ext and rel.endswith(ext):
        return f"{rel[: -len(ext)]} ({n}){ext}"
    return f"{rel} ({n})"


async def _free_name(
    session: AsyncSession, live: LiveSet, root: MediaRoot, rendered: str, ext: str,
) -> str:
    """``rendered``, or the first suffixed variant that is neither on disk
    nor referenced by another set on the root. Returns the set's current
    ``audio_path`` if that is the first candidate it reaches, so a set
    already at ``x (2).flac`` stays there."""
    suffixed = (_with_suffix(rendered, ext, n) for n in range(2, _MAX_SUFFIX + 1))
    for candidate in itertools.chain([rendered], suffixed):
        if candidate == live.audio_path:
            return candidate
        target = _path(root, candidate)
        taken = (
            target.exists() or target.is_symlink()
            or await path_in_use(session, root.id, candidate, exclude_live_set_id=live.id)
        )
        if not taken:
            return candidate
    raise RuntimeError(f"no free name for {rendered!r} after {_MAX_SUFFIX} tries")


def _tidy_originals_dir(directory: Path, root: MediaRoot) -> None:
    """Remove ``<root>/originals/<id>/`` once its last file has moved out."""
    if directory.parent != Path(root.host_path) / "originals":
        return
    try:
        directory.rmdir()  # only succeeds when empty
    except OSError:
        pass


async def apply_naming_to_set(
    session: AsyncSession, live: LiveSet, root: MediaRoot,
) -> NamingOutcome:
    """Move ``live``'s audio file to the path ``root``'s naming template
    renders for it. Commits ``session`` when it renames.

    Returns ``"unchanged"`` when the file is already at its template path,
    ``"skipped"`` when the root has no template, the template renders no
    usable file name, or the source file is missing, and ``"renamed"``
    otherwise. Raises ``ValueError`` when a path escapes the root.
    """
    if live.media_root_id != root.id:
        raise ValueError(f"set {live.id} is not on media root {root.id}")
    template = root.naming_template
    if not template:
        return "skipped"

    old_rel = live.audio_path
    ext = PurePosixPath(old_rel).suffix
    rendered = render_filename(template, live, ext=ext)
    if not rendered or PurePosixPath(rendered).name in ("", ext):
        logger.warning("naming: template %r renders no file name for set %s", template, live.id)
        return "skipped"
    if rendered == old_rel:
        return "unchanged"

    old_abs = _path(root, old_rel)
    if not old_abs.is_file():
        logger.warning("naming: source file missing for set %s: %s", live.id, old_rel)
        return "skipped"

    new_rel = await _free_name(session, live, root, rendered, ext)
    if new_rel == old_rel:
        return "unchanged"
    new_abs = _path(root, new_rel)

    place_audio_file(old_abs, new_abs)
    if new_abs.stat().st_size != old_abs.stat().st_size:
        # Leave both names; the row still points at the old one.
        raise OSError(f"placed copy {new_abs} differs in size from {old_abs}")
    live.audio_path = new_rel
    try:
        await session.commit()
    except Exception:
        # The new name is left on disk: if the commit did land despite the
        # error, the row points at it. The old name is never touched here.
        await session.rollback()
        raise

    try:
        if await path_in_use(session, root.id, old_rel, exclude_live_set_id=None):
            logger.info("naming: keeping %s, another set uses it", old_rel)
        else:
            old_abs.unlink(missing_ok=True)
            _tidy_originals_dir(old_abs.parent, root)
    except Exception:
        logger.exception("naming: post-commit cleanup of %s failed", old_abs)
    logger.info("naming: set %s renamed %s -> %s", live.id, old_rel, new_rel)
    return "renamed"


async def apply_naming_one(set_id: str) -> NamingOutcome:
    """Apply the template to one set. The set's row is locked while its file
    moves, so two runs for the same set (publish and an edit) serialise and
    the second finds it ``"unchanged"``."""
    if "DATABASE_URL" in os.environ:
        init_engine(os.environ["DATABASE_URL"])
    try:
        sid = uuid.UUID(set_id)
    except ValueError:
        return "skipped"

    async with session_factory()() as s:
        live = (await s.execute(
            select(LiveSet).where(LiveSet.id == sid)
            .with_for_update(of=LiveSet)
            .execution_options(populate_existing=True)
        )).scalar_one_or_none()
        # A recycled set's files belong to the purge job.
        if live is None or live.deleted_at is not None:
            return "skipped"
        root = await s.get(MediaRoot, live.media_root_id)
        if root is None:
            return "skipped"
        return await apply_naming_to_set(s, live, root)


def run_apply_naming_one(set_id: str) -> str:
    """RQ entry point."""
    return run_job(apply_naming_one(set_id))


def enqueue_apply_naming(set_id: uuid.UUID) -> None:
    """Queue :func:`run_apply_naming_one` for ``set_id``. Never raises: a
    missing rename must not fail the publish or upgrade that asked for it."""
    try:
        from redis import Redis
        from rq import Queue

        redis = Redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        Queue("default", connection=redis).enqueue(
            "setvault_core.jobs.apply_naming.run_apply_naming_one", str(set_id),
        )
    except Exception:
        logger.exception("naming: enqueue failed for set %s", set_id)
