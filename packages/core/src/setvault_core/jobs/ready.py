from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_core import triggers
from setvault_core.config import redis_url
from setvault_core.db import init_engine, session_factory
from setvault_core.jobs.apply_naming import enqueue_apply_naming
from setvault_core.models.catalog import LiveSet, MediaRoot
from setvault_core.models.library_webhook import LibraryWebhook
from setvault_core.progress import ProgressEvent, publish
from setvault_core.services.activity import record

logger = logging.getLogger(__name__)


async def fan_out_webhooks(live: LiveSet, event: str) -> None:
    """Enqueue a dispatch job for every enabled webhook whose ``events``
    array includes ``event``. Errors are logged but never re-raise — the
    set-publish flow must not block on webhook config issues."""
    try:
        from redis import Redis
        from rq import Queue

        async with session_factory()() as s:  # type: AsyncSession
            rows = (await s.execute(
                select(LibraryWebhook).where(LibraryWebhook.enabled.is_(True))
            )).scalars().all()

        if not rows:
            return

        redis = Redis.from_url(redis_url())
        queue = Queue("default", connection=redis)
        for wh in rows:
            if event not in (wh.events or []):
                continue
            queue.enqueue(
                "setvault_core.jobs.webhook_dispatch.run_dispatch_webhook",
                webhook_id=str(wh.id),
                event=event,
                set_slug=live.slug,
                set_id=str(live.id),
                title=live.title,
            )
    except Exception:
        logger.exception("webhook fan-out failed for %s", event)


async def publish_live_set(s: AsyncSession, live: LiveSet) -> None:
    """Flip ``live`` to published and record the activity event. The caller
    commits, then calls ``fan_out_webhooks(live, "set.published")``.

    When the set's media root has a naming template, the single-set rename
    job is queued as well (P2a A4). It writes only ``audio_path`` and takes
    the set's row lock, so it is safe whether it runs before or after the
    caller's commit.
    """
    live.status = "published"
    await record(
        s,
        kind="set.published",
        subject_type="LiveSet",
        subject_id=live.id,
        user_id=live.uploaded_by,
    )
    root = await s.get(MediaRoot, live.media_root_id)
    if root is not None and root.naming_template:
        enqueue_apply_naming(live.id)


@dataclass(frozen=True)
class ArrivalResult:
    """What the final stage did with a set: ``outcome`` is the
    ``decide`` outcome, ``message`` the line shown in progress/jobs."""
    outcome: str
    message: str


async def finish_arrival(
    live_set_id: str, *, upgrade_target_id: uuid.UUID | None = None,
    trigger: str = triggers.UPLOAD, candidate_source_kind: str | None = None,
    candidate_external_id: str | None = None,
) -> ArrivalResult:
    """Final pipeline stage. Decides the arrival first
    (``services/upgrade_decision``): it may upgrade the set it duplicates, be
    held as a draft for the admin Duplicates page, or (upgrade-attempt rips)
    be discarded. Only an arrival with nothing to decide is published."""
    # Lazy: services/set_upgrade imports this module for fan_out_webhooks.
    from setvault_core.services.upgrade_decision import decide

    if "DATABASE_URL" in os.environ:
        init_engine(os.environ["DATABASE_URL"])

    published: LiveSet | None = None
    async with session_factory()() as s:
        live = await s.get(LiveSet, uuid.UUID(live_set_id))
        if live is None:
            return ArrivalResult("held", "set no longer exists")
        decision = await decide(
            s, live, upgrade_target_id=upgrade_target_id, trigger=trigger,
            candidate_source_kind=candidate_source_kind,
            candidate_external_id=candidate_external_id,
        )
        if decision.outcome == "publish":
            await publish_live_set(s, live)
            await s.commit()
            published = live

    result = ArrivalResult(decision.outcome, decision.message)
    publish(ProgressEvent(
        kind="ready", live_set_id=live_set_id, job_id=live_set_id,
        progress_pct=100, message=result.message,
    ))

    # Library refresh webhooks (§J15). Fans out to enabled webhook rows whose
    # `events` array includes `set.published`. (An upgrade fans out on its own.)
    if published is not None:
        await fan_out_webhooks(published, "set.published")
    return result


async def mark_ready(
    live_set_id: str, *, trigger: str = triggers.UPLOAD,
) -> bool:
    """:func:`finish_arrival`, returning whether the set was published."""
    result = await finish_arrival(live_set_id, trigger=trigger)
    return result.outcome == "publish"
