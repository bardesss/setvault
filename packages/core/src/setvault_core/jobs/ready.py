from __future__ import annotations

import logging
import os
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_core.db import init_engine, run_job, session_factory
from setvault_core.models.catalog import LiveSet
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

        redis = Redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
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
    commits, then calls ``fan_out_webhooks(live, "set.published")``."""
    live.status = "published"
    await record(
        s,
        kind="set.published",
        subject_type="LiveSet",
        subject_id=live.id,
        user_id=live.uploaded_by,
    )


async def mark_ready(live_set_id: str) -> bool:
    """Final pipeline stage. Publishes the set unless the fingerprint stage
    flagged it as a duplicate: those stay drafts for an admin to keep or
    discard (admin Duplicates page). Returns whether the set was published."""
    if "DATABASE_URL" in os.environ:
        init_engine(os.environ["DATABASE_URL"])

    async with session_factory()() as s:
        live = await s.get(LiveSet, uuid.UUID(live_set_id))
        if live is None:
            return False
        if live.duplicate_of is not None:
            publish(ProgressEvent(
                kind="ready", live_set_id=live_set_id, job_id=live_set_id,
                progress_pct=100, message="held for review: duplicate of an existing set",
            ))
            return False
        await publish_live_set(s, live)
        await s.commit()
        published = live

    publish(ProgressEvent(
        kind="ready", live_set_id=live_set_id, job_id=live_set_id,
        progress_pct=100, message="published",
    ))

    # Library refresh webhooks (§J15). Fans out to enabled webhook rows whose
    # `events` array includes `set.published`.
    await fan_out_webhooks(published, "set.published")
    return True


def mark_ready_sync(live_set_id: str) -> None:
    run_job(mark_ready(live_set_id))
