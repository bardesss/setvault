"""Library webhook events for sets leaving, re-entering or changing in the
library (``set.updated``, ``set.deleted``, ``set.restored``, ``set.purged``).

Only published sets are announced: a draft was never announced as published,
so its edits, discards and purges stay private. Every call site fires after
its commit. All functions here are async and never raise.
"""
from __future__ import annotations

import logging

from setvault_core.models.catalog import LiveSet

logger = logging.getLogger(__name__)


async def _announce(
    event: str, *, set_slug: str, set_id: str, title: str,
) -> None:
    try:
        # Lazy: jobs.ready pulls in the queue and dispatch stack, which this
        # light module must not import at load time.
        from setvault_core.jobs.ready import fan_out_webhook_event

        await fan_out_webhook_event(
            event, set_slug=set_slug, set_id=set_id, title=title,
        )
    except Exception:
        logger.exception("webhook announce failed for %s", event)


async def _announce_live(
    live: LiveSet, event: str, *, announce: bool, title: str | None = None,
) -> None:
    if announce:
        await _announce(
            event, set_slug=live.slug, set_id=str(live.id),
            title=live.title if title is None else title,
        )

async def announce_updated(live: LiveSet) -> None:
    """``set.updated`` for an edited published set."""
    await _announce_live(
        live, "set.updated", announce=live.status == "published",
    )


async def announce_recycled(
    live: LiveSet, *, was_published: bool | None = None, title: str | None = None,
) -> None:
    """``set.deleted`` for a set that went to the recycle bin.

    ``was_published`` and ``title`` are for callers that rewrite the status
    and title as part of recycling (merge loser, upgrade swap): they capture
    both first. Left None, the set's current values are used.
    """
    announce = live.status == "published" if was_published is None else was_published
    await _announce_live(live, "set.deleted", announce=announce, title=title)

async def announce_restored(live: LiveSet) -> None:
    """``set.restored`` for a published set taken out of the recycle bin."""
    await _announce_live(
        live, "set.restored", announce=live.status == "published",
    )


async def announce_purged(
    *, was_published: bool, set_slug: str, set_id: str, title: str,
) -> None:
    """``set.purged`` after a hard delete. The caller captures the values
    (and ``was_published``) before ``session.delete``."""
    if not was_published:
        return
    await _announce("set.purged", set_slug=set_slug, set_id=set_id, title=title)
