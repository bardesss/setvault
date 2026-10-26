"""Enqueue outbound email through the Phase 2B notification-connector framework.

Lives in ``packages/core`` so the notification dispatcher (also in packages/core)
can reach it without importing upward into apps/web. Web and worker code both
call this directly, passing ``redis_url``.
"""
from __future__ import annotations

import logging
from functools import lru_cache

from redis import Redis
from rq import Queue
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_core.models.system import NotificationConnector

logger = logging.getLogger(__name__)


@lru_cache(maxsize=8)
def _queue(redis_url: str) -> Queue:
    return Queue("default", connection=Redis.from_url(redis_url))


async def enqueue_email(
    session: AsyncSession,
    *,
    redis_url: str,
    to: str,
    subject: str,
    text: str,
) -> bool:
    """Enqueue ``send_email_job`` via the first enabled SMTP connector.

    Returns True if a job was queued; False if no SMTP connector exists (the
    caller is expected to fall back to a copy-paste link in that case) or Redis
    is unreachable.
    """
    row = (
        await session.execute(
            select(NotificationConnector)
            .where(
                NotificationConnector.kind == "smtp",
                NotificationConnector.enabled.is_(True),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        return False
    try:
        _queue(redis_url).enqueue(
            "setvault_core.jobs.email.send_email_job",
            connector_id=str(row.id),
            to=to,
            subject=subject,
            text=text,
        )
    except Exception:
        logger.exception("failed to enqueue email job")
        return False
    return True
