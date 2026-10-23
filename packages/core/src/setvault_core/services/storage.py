from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path
from typing import Literal

from sqlalchemy import exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_core.models.catalog import LiveSet

HealthStatus = Literal["ok", "unreachable", "readonly", "near_full", "unknown"]


def probe(host_path: str, *, near_full_pct: float = 95.0) -> HealthStatus:
    p = Path(host_path)
    if not p.exists():
        return "unreachable"
    if not os.access(p, os.W_OK):
        return "readonly"
    try:
        usage = shutil.disk_usage(p)
    except OSError:
        return "unknown"
    pct = (usage.used / usage.total) * 100 if usage.total else 0
    if pct >= near_full_pct:
        return "near_full"
    return "ok"


def resolve_set_path(host_root: str, relative: str) -> Path:
    root = Path(host_root).resolve()
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"path {relative!r} escapes media root") from exc
    return candidate


PlacementMode = Literal["hardlinked", "copied"]


def _copy_exclusive(src: Path, dst: Path) -> None:
    """Copy ``src`` to ``dst`` without ever replacing an existing ``dst``.

    The copy goes to a uniquely named tmp in dst's directory, which is then
    hardlinked to ``dst`` (fails with FileExistsError if the name is taken,
    atomically) and removed. Where the filesystem has no hardlinks, ``dst``
    is reserved with an exclusive create and the tmp renamed over that
    placeholder, which only this call owns.
    """
    tmp = dst.parent / f".{dst.name}.{uuid.uuid4().hex}.tmp"
    try:
        shutil.copy2(src, tmp)
        try:
            os.link(tmp, dst)
        except FileExistsError:
            raise
        except OSError:
            # No hardlink support: reserve the name, then fill it atomically.
            fd = os.open(dst, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            try:
                os.replace(tmp, dst)
            except OSError:
                dst.unlink(missing_ok=True)  # our own empty placeholder
                raise
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def place_audio_file(src: Path, dst: Path, *, overwrite: bool = True) -> PlacementMode:
    """Place ``src`` at ``dst`` using a hardlink when on the same filesystem,
    otherwise a copy followed by an atomic rename. The destination's parent
    directory is created if missing.

    Returns the mode used so the caller can record it on the audit event
    (``pipeline.placement_mode``). Cross-filesystem moves use a ``.tmp``
    sibling + ``os.rename`` so the final dst either fully exists or doesn't
    exist — never a half-written file.

    Raises FileNotFoundError if ``src`` doesn't exist; OSError on permission /
    quota failures (passes through). ``src`` is never deleted by this call —
    on hardlink we keep both names; on copy the caller decides whether to
    unlink the original.

    ``overwrite=False`` makes the placement an exclusive create: if ``dst``
    exists (or appears concurrently) it raises FileExistsError and leaves
    ``dst`` untouched. The default replaces an existing ``dst``.
    """
    src = Path(src)
    dst = Path(dst)
    if not src.exists():
        raise FileNotFoundError(f"source {src} does not exist")
    dst.parent.mkdir(parents=True, exist_ok=True)

    same_fs = False
    try:
        same_fs = src.stat().st_dev == dst.parent.stat().st_dev
    except OSError:
        # dst.parent may have just been created; stat() should succeed but
        # if it doesn't, fall through to the copy path.
        same_fs = False

    if same_fs:
        # Hardlink — instant, zero extra disk. os.link won't overwrite: with
        # overwrite=False an existing dst raises FileExistsError; otherwise a
        # stale dst is removed first.
        if overwrite and dst.exists():
            dst.unlink()
        os.link(src, dst)
        return "hardlinked"

    if not overwrite:
        _copy_exclusive(src, dst)
        return "copied"

    # Cross-filesystem: copy to a sibling .tmp file then atomic-rename.
    tmp = dst.with_suffix(dst.suffix + ".tmp")
    try:
        shutil.copy2(src, tmp)
        os.replace(tmp, dst)  # atomic on the same fs (tmp is on dst's fs)
    except OSError:
        # Clean up the partial tmp if we left one behind.
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        raise
    return "copied"


async def path_in_use(
    session: AsyncSession, media_root_id: uuid.UUID, rel_path: str,
    *, exclude_live_set_id: uuid.UUID | None,
) -> bool:
    """True if any LiveSet other than ``exclude_live_set_id`` on this media
    root references ``rel_path`` as its audio, stream, waveform or thumb file,
    whatever its status (deleted or not).

    Every code path that deletes set files checks this first: after a quality
    upgrade (services/set_upgrade.py) the live set and its recycled old copy
    can end up naming the same file, e.g. once the live set's stream is
    regenerated at ``stream/<id>.opus``.
    """
    conds = [
        LiveSet.media_root_id == media_root_id,
        or_(LiveSet.audio_path == rel_path, LiveSet.streaming_path == rel_path,
            LiveSet.waveform_path == rel_path, LiveSet.thumb_path == rel_path),
    ]
    if exclude_live_set_id is not None:
        conds.append(LiveSet.id != exclude_live_set_id)
    stmt = select(exists().where(*conds))
    return bool(await session.scalar(stmt))
