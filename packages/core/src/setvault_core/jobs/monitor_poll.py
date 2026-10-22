"""RQ job: poll one monitor for new content.

query monitors -> search_all_sources (or a single source if source_kind is set);
entity monitors -> search_source for the pinned kind using the external_id as the
search term. SourceRateLimitedError / SourceDisabledError are swallowed (skip this
poll); results are handed to the discovery service which dedups, auto-ingests, notifies.
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import UTC, datetime

from setvault_ingest_sources.base import SourceError
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_core.db import init_engine, run_job, session_factory
from setvault_core.models.monitors import Monitor
from setvault_core.services.discoveries import process_candidates
from setvault_core.services.ingest_sources import (
    SourceDisabledError,
    SourceRateLimitedError,
    search_all_sources,
    search_source,
)
from setvault_core.services.rip_enqueue import enqueue_rip

logger = logging.getLogger(__name__)

DATABASE_URL_ENV = "DATABASE_URL"


async def poll_monitor(session: AsyncSession, *, monitor_id: uuid.UUID) -> dict:
    monitor = await session.get(Monitor, monitor_id)
    if monitor is None or not monitor.enabled:
        return {"auto_ingested": 0, "pending_review": 0, "skipped_duplicate": 0}

    try:
        if monitor.kind == "entity":
            candidates = await search_source(
                session, kind=monitor.source_kind, query=monitor.external_id or "", limit=20,
            )
        elif monitor.source_kind:
            candidates = await search_source(
                session, kind=monitor.source_kind, query=monitor.query_text or "", limit=20,
            )
        else:
            result = await search_all_sources(
                session, query=monitor.query_text or "", limit_per_source=10,
            )
            candidates = result.candidates
    except (SourceRateLimitedError, SourceDisabledError):
        candidates = []
    except SourceError as exc:
        # search_source already recorded the failure (count, last_error, auto
        # disable); treat it as "no candidates" so the poll reaches the commit
        # below and that bookkeeping is persisted instead of rolled back.
        logger.warning("monitor %s: source search failed: %s", monitor.id, exc)
        candidates = []

    summary = await process_candidates(session, monitor=monitor, candidates=candidates)
    rip_jobs = summary.pop("rip_jobs", [])
    monitor.last_checked_at = datetime.now(UTC)
    await session.flush()
    await session.commit()
    # Commit first so workers can see the RipJobs. A failed enqueue marks that
    # job failed (enqueue_rip) and must not abort the other rips.
    for rip_job in rip_jobs:
        await enqueue_rip(session, rip_job)
    return summary


def run_poll_monitor(*, monitor_id: str) -> dict:
    """RQ entry point."""
    async def _main() -> dict:
        if DATABASE_URL_ENV in os.environ:
            init_engine(os.environ[DATABASE_URL_ENV])
        async with session_factory()() as s:
            return await poll_monitor(s, monitor_id=uuid.UUID(monitor_id))

    return run_job(_main())
