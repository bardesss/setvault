"""Bulk-action worker job (§G7).

Three actions land for v0.1.0:

  - ``soft_delete`` — move sets to recycle bin (sets ``deleted_at`` + a
    14-day ``purge_after_at``, mirroring the single-set soft-delete flow).
  - ``retag`` — add or remove tags across the selection. ``params``:
    ``{"add": ["techno", "minimal"], "remove": ["old-tag"]}``.
  - ``move_root`` — assign all selected sets to a different
    ``MediaRoot.id``. ``params``: ``{"target_media_root_id": "<uuid>"}``.
    Moves the set's audio/stream/waveform/thumb files to the same relative
    paths under the target root (hardlink or size-verified copy, never
    overwriting), re-checks the row under lock (a set whose paths changed
    meanwhile is skipped and its copies removed), commits, then unlinks the
    old names no other set uses.

Per-set failures are isolated (logged + counted; the rest of the batch
proceeds) and every set is committed on its own. The summary dict is the job return value.
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_core.db import init_engine, run_job, session_factory
from setvault_core.models.catalog import LiveSet, LiveSetTag, MediaRoot, Tag
from setvault_core.services.audit import log as audit_log
from setvault_core.services.storage import (
    path_in_use,
    place_audio_file,
    probe,
    resolve_set_path,
)

logger = logging.getLogger(__name__)

PURGE_GRACE_DAYS = 14


async def _soft_delete_one(s: AsyncSession, live: LiveSet, *, actor_id: uuid.UUID | None) -> None:
    if live.deleted_at is not None:
        return
    now = datetime.now(UTC)
    live.deleted_at = now
    live.purge_after_at = now + timedelta(days=PURGE_GRACE_DAYS)
    await audit_log(
        s,
        actor_user_id=actor_id,
        action="set.bulk_soft_deleted",
        target_type="LiveSet",
        target_id=str(live.id),
    )


async def _retag_one(
    s: AsyncSession, live: LiveSet, *,
    add_tags: list[str], remove_tags: list[str], actor_id: uuid.UUID | None,
) -> None:
    # Resolve tag names → Tag rows. Create unknown tags as we go (matches the
    # existing replace_tags pattern in services/sets.py).
    if add_tags:
        existing = {t.name for t in (await s.execute(
            select(Tag).where(Tag.name.in_(add_tags))
        )).scalars()}
        for name in set(add_tags) - existing:
            slug = name.lower().replace(" ", "-")[:80] or "tag"
            s.add(Tag(name=name, slug=slug, kind="custom"))
        await s.flush()
        tag_rows = {t.name: t for t in (await s.execute(
            select(Tag).where(Tag.name.in_(add_tags))
        )).scalars()}
        current = {row.tag_id for row in (await s.execute(
            select(LiveSetTag).where(LiveSetTag.live_set_id == live.id)
        )).scalars()}
        for name in add_tags:
            t = tag_rows.get(name)
            if t is not None and t.id not in current:
                s.add(LiveSetTag(live_set_id=live.id, tag_id=t.id))
    if remove_tags:
        rm_ids = [t.id for t in (await s.execute(
            select(Tag).where(Tag.name.in_(remove_tags))
        )).scalars()]
        if rm_ids:
            await s.execute(
                LiveSetTag.__table__.delete().where(
                    LiveSetTag.live_set_id == live.id,
                    LiveSetTag.tag_id.in_(rm_ids),
                ),
            )
    await audit_log(
        s,
        actor_user_id=actor_id,
        action="set.bulk_retagged",
        target_type="LiveSet",
        target_id=str(live.id),
        after={"add": add_tags, "remove": remove_tags},
    )


class MoveRootError(Exception):
    """A set can't be moved; nothing was changed for it."""


_PATH_COLUMNS = ("audio_path", "streaming_path", "waveform_path", "thumb_path")


def _nested_or_same(a: Path, b: Path) -> bool:
    return a == b or a in b.parents or b in a.parents


def _plan_move(old_host: str, target_host: str, rels: list[str]) -> list[tuple[str, Path, Path]]:
    """Check everything before placing anything: roots are disjoint, every
    source exists, and no destination (or its ``.tmp`` sibling, which
    place_audio_file's copy path writes) exists. Raises MoveRootError."""
    if _nested_or_same(Path(old_host).resolve(), Path(target_host).resolve()):
        raise MoveRootError("current and target root are the same or nested")
    plan: list[tuple[str, Path, Path]] = []
    for rel in rels:
        try:
            src = resolve_set_path(old_host, rel)
            dst = resolve_set_path(target_host, rel)
        except ValueError as exc:
            raise MoveRootError(str(exc)) from exc
        if not src.is_file():
            raise MoveRootError(f"source missing: {rel}")
        tmp = dst.with_suffix(dst.suffix + ".tmp")
        if os.path.lexists(dst) or os.path.lexists(tmp):
            raise MoveRootError(f"destination exists: {rel}")
        if src == dst:  # impossible with disjoint roots; never hand it to place_audio_file
            raise MoveRootError(f"source and destination are the same: {rel}")
        plan.append((rel, src, dst))
    return plan


def _place_all(plan: list[tuple[str, Path, Path]], placed: list[Path]) -> None:
    """Place each file and verify its size (place_audio_file doesn't).
    Appends every placed destination to ``placed`` so the caller can clean up."""
    for rel, src, dst in plan:
        if os.path.lexists(dst):
            raise MoveRootError(f"destination appeared: {rel}")
        place_audio_file(src, dst)
        placed.append(dst)
        if dst.stat().st_size != src.stat().st_size:
            raise MoveRootError(f"size mismatch after placing {rel}")


def _unlink(p: Path) -> None:
    p.unlink(missing_ok=True)


def _resolved_roots(roots: list[MediaRoot]) -> list[tuple[uuid.UUID, Path]]:
    return [(r.id, Path(r.host_path).resolve()) for r in roots]


def _remove_placed(placed: list[Path]) -> None:
    """Remove copies this job created. Each was verified absent before it was
    placed, so it is ours to delete (for a hardlink the source keeps its name)."""
    for dst in reversed(placed):
        try:
            dst.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            logger.warning("bulk move_root: cleanup of %s failed: %s", dst, exc)


async def _file_in_use_elsewhere(
    s: AsyncSession, src: Path, rel: str, *, old_root_id: uuid.UUID,
    roots: list[tuple[uuid.UUID, Path]], live_id: uuid.UUID,
) -> bool:
    """True if any other set still names ``src``. MediaRoot.host_path isn't
    unique (and roots may nest), so check every root whose directory contains
    the file, not just the set's own root."""
    if await path_in_use(s, old_root_id, rel, exclude_live_set_id=live_id):
        return True
    for root_id, base in roots:
        try:
            other_rel = src.relative_to(base).as_posix()
        except ValueError:
            continue
        if await path_in_use(s, root_id, other_rel, exclude_live_set_id=live_id):
            return True
    return False


async def _move_root_one(
    s: AsyncSession, live: LiveSet, *,
    target_id: uuid.UUID, target_host: str,
    roots: list[tuple[uuid.UUID, Path]], actor_id: uuid.UUID | None,
) -> bool:
    """Move one set's files to the target root and repoint it.

    Returns False when the set is already on the target (no-op). Raises
    MoveRootError before anything is placed, or re-raises any later failure
    after removing the copies placed so far. Old files are unlinked only after
    the commit, and only when no other set references them.
    """
    if live.media_root_id == target_id:
        return False
    live_id = live.id
    old_root = await s.get(MediaRoot, live.media_root_id)
    if old_root is None:
        raise MoveRootError("current media root not found")
    old_root_id, old_host = old_root.id, old_root.host_path
    read = {c: getattr(live, c) for c in (*_PATH_COLUMNS, "media_root_id")}
    rels = list(dict.fromkeys(r for r in (read[c] for c in _PATH_COLUMNS) if r))
    plan = _plan_move(old_host, target_host, rels)

    placed: list[Path] = []
    try:
        # Copy without a row lock, so a long copy doesn't block edits...
        await asyncio.to_thread(_place_all, plan, placed)
        # ...then re-check under lock: a rename, transcode or upgrade that
        # committed meanwhile changed which files the row names, and the
        # copies would be stale or incomplete.
        locked = (await s.execute(
            select(LiveSet).where(LiveSet.id == live_id)
            .with_for_update(of=LiveSet)
            .execution_options(populate_existing=True)
        )).scalar_one_or_none()
        if locked is None:
            raise MoveRootError("set vanished during the move")
        changed = [c for c, v in read.items() if getattr(locked, c) != v]
        if changed:
            raise MoveRootError(f"set changed during the move ({', '.join(changed)})")
        live = locked
        live.media_root_id = target_id
        await audit_log(
            s,
            actor_user_id=actor_id,
            action="set.bulk_moved_root",
            target_type="LiveSet",
            target_id=str(live_id),
            before={"media_root_id": str(old_root_id)},
            after={"media_root_id": str(target_id)},
        )
        await s.commit()
    except BaseException:
        _remove_placed(placed)
        raise

    # Committed: the set now lives on the target. Drop the old names unless
    # another set still uses them. A failure here only leaves a stale copy.
    for rel, src, _dst in plan:
        try:
            if await _file_in_use_elsewhere(
                s, src, rel, old_root_id=old_root_id, roots=roots, live_id=live_id,
            ):
                logger.info("bulk move_root: keeping %s, still in use", src)
                continue
            _unlink(src)
        except Exception as exc:
            logger.warning("bulk move_root: unlink of old %s failed: %s", src, exc)
    return True


async def bulk_action(
    *,
    action: str,
    set_ids: list[str],
    params: dict,
    actor_user_id: str | None,
) -> dict:
    if "DATABASE_URL" in os.environ:
        init_engine(os.environ["DATABASE_URL"])

    actor = uuid.UUID(actor_user_id) if actor_user_id else None
    base = {"action": action, "processed": 0, "errors": 0}
    if action == "move_root":
        target = params.get("target_media_root_id")
        if not target:
            return {**base, "reason": "missing target_media_root_id"}
        try:
            target_uuid = uuid.UUID(target)
        except ValueError:
            return {**base, "reason": "invalid target_media_root_id"}
    else:
        target_uuid = None

    add_tags = list(params.get("add", []) or []) if action == "retag" else []
    remove_tags = list(params.get("remove", []) or []) if action == "retag" else []

    summary: dict = {"action": action, "processed": 0, "errors": 0, "failed": []}
    if action == "move_root":
        summary["moved"] = []
        summary["skipped"] = []

    async with session_factory()() as s:
        target_host = ""
        roots: list[tuple[uuid.UUID, Path]] = []
        if action == "move_root" and target_uuid is not None:
            root = await s.get(MediaRoot, target_uuid)
            if root is None:
                return {**summary, "reason": "target MediaRoot not found"}
            if not root.enabled:
                return {**summary, "reason": "target MediaRoot is disabled"}
            health = probe(root.host_path)
            if health in ("unreachable", "readonly", "unknown"):
                return {**summary, "reason": f"target MediaRoot is {health}"}
            # Plain values only: a per-item rollback expires ORM objects.
            target_host = root.host_path
            roots = _resolved_roots(list((await s.execute(select(MediaRoot))).scalars()))

        for raw_id in set_ids:
            try:
                live_id = uuid.UUID(raw_id)
            except ValueError:
                summary["errors"] += 1
                summary["failed"].append({"id": raw_id, "reason": "invalid id"})
                continue
            live = await s.get(LiveSet, live_id)
            if live is None or (live.deleted_at is not None and action != "soft_delete"):
                summary["errors"] += 1
                summary["failed"].append({"id": raw_id, "reason": "not found"})
                continue
            slug = live.slug

            try:
                if action == "soft_delete":
                    await _soft_delete_one(s, live, actor_id=actor)
                elif action == "retag":
                    await _retag_one(
                        s, live,
                        add_tags=add_tags, remove_tags=remove_tags,
                        actor_id=actor,
                    )
                elif action == "move_root" and target_uuid is not None:
                    moved = await _move_root_one(
                        s, live,
                        target_id=target_uuid, target_host=target_host,
                        roots=roots, actor_id=actor,
                    )
                    summary["moved" if moved else "skipped"].append(slug)
                else:
                    summary["errors"] += 1
                    continue
                # Commit per item so a later failure can't roll this one back.
                await s.commit()
                summary["processed"] += 1
            except MoveRootError as exc:
                summary["errors"] += 1
                summary["failed"].append({"slug": slug, "reason": str(exc)})
                logger.warning("bulk_action move_root skipped %s: %s", slug, exc)
                await s.rollback()
            except Exception as exc:
                summary["errors"] += 1
                summary["failed"].append({"slug": slug, "reason": type(exc).__name__})
                logger.exception("bulk_action %s failed for %s", action, live_id)
                await s.rollback()

    return summary


def run_bulk_action(
    *,
    action: str,
    set_ids: list[str],
    params: dict | None = None,
    actor_user_id: str | None = None,
) -> dict:
    return run_job(bulk_action(
        action=action, set_ids=set_ids,
        params=params or {}, actor_user_id=actor_user_id,
    ))
