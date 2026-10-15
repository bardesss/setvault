"""Bulk-action worker job (§G7).

Three actions land for v0.1.0:

  - ``soft_delete`` — move sets to recycle bin (sets ``deleted_at`` + a
    14-day ``purge_after_at``, mirroring the single-set soft-delete flow).
  - ``retag`` — add or remove tags across the selection. ``params``:
    ``{"add": ["techno", "minimal"], "remove": ["old-tag"]}``.
  - ``move_root`` — assign all selected sets to a different
    ``MediaRoot.id``. ``params``: ``{"target_media_root_id": "<uuid>"}``.
    Does NOT move files on disk for v0.1.0 — admin can run the new root's
    ``naming_template`` reapply afterwards if they want files to follow.

Per-set failures are isolated (logged + counted; the rest of the batch
proceeds). The summary dict is the job return value.
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_core.db import init_engine, run_job, session_factory
from setvault_core.models.catalog import LiveSet, LiveSetTag, MediaRoot, Tag
from setvault_core.services.audit import log as audit_log

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


async def _move_root_one(
    s: AsyncSession, live: LiveSet, *,
    target_media_root_id: uuid.UUID, actor_id: uuid.UUID | None,
) -> None:
    if live.media_root_id == target_media_root_id:
        return
    before_root = live.media_root_id
    live.media_root_id = target_media_root_id
    await audit_log(
        s,
        actor_user_id=actor_id,
        action="set.bulk_moved_root",
        target_type="LiveSet",
        target_id=str(live.id),
        before={"media_root_id": str(before_root)},
        after={"media_root_id": str(target_media_root_id)},
    )


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

    summary = {"action": action, "processed": 0, "errors": 0}

    async with session_factory()() as s:
        if action == "move_root" and target_uuid is not None:
            root = await s.get(MediaRoot, target_uuid)
            if root is None:
                return {**summary, "reason": "target MediaRoot not found"}

        for raw_id in set_ids:
            try:
                live_id = uuid.UUID(raw_id)
            except ValueError:
                summary["errors"] += 1
                continue
            live = await s.get(LiveSet, live_id)
            if live is None or (live.deleted_at is not None and action != "soft_delete"):
                summary["errors"] += 1
                continue

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
                    await _move_root_one(
                        s, live,
                        target_media_root_id=target_uuid, actor_id=actor,
                    )
                else:
                    summary["errors"] += 1
                    continue
                summary["processed"] += 1
            except Exception:
                summary["errors"] += 1
                logger.exception("bulk_action %s failed for %s", action, live_id)
                await s.rollback()

        await s.commit()

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
