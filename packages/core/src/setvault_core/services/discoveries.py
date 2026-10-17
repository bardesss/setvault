"""Turn a monitor's search candidates into discovery rows + notifications.

Per candidate: skip if already a discovery for this monitor; else score
confidence (entity monitors are always high), auto-ingest high-confidence
candidates up to the monitor's per_poll_cap (rest -> pending_review), and write
one `discovery` InAppNotification summarizing the poll.
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import UTC, datetime

from setvault_ingest_sources.base import Candidate
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_core.models.engagement_3c import InAppNotification
from setvault_core.models.monitors import Monitor, MonitorDiscovery
from setvault_core.services.monitor_match import score_confidence

logger = logging.getLogger(__name__)


async def _existing_keys(session: AsyncSession, monitor_id: uuid.UUID) -> set[tuple[str, str]]:
    rows = (await session.execute(
        select(MonitorDiscovery.source_kind, MonitorDiscovery.external_id)
        .where(MonitorDiscovery.monitor_id == monitor_id)
    )).all()
    return {(r[0], r[1]) for r in rows}


async def _ingest_candidate(
    session: AsyncSession, *, monitor: Monitor, candidate: Candidate,
) -> uuid.UUID | None:
    """Submit the candidate's webpage_url through the existing url-rip pipeline
    and enqueue the rip job. Returns the RipJob id, or None on failure."""
    from redis import Redis
    from rq import Queue

    from setvault_core.jobs.url_rip_job import RIP_JOB_TIMEOUT
    from setvault_core.services.url_rip import DuplicateRipError, submit_rip

    try:
        job = await submit_rip(session, user_id=monitor.owner_user_id, url=candidate.webpage_url)
    except DuplicateRipError as e:
        return e.existing.id
    except Exception:
        logger.exception(
            "monitor %s: auto-ingest failed for %s", monitor.id, candidate.webpage_url,
        )
        return None
    redis = Redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
    Queue("default", connection=redis).enqueue(
        "setvault_core.jobs.url_rip_job.run_rip_job", rip_job_id=str(job.id),
        job_timeout=RIP_JOB_TIMEOUT,
    )
    return job.id


async def _notify_owner(
    session: AsyncSession, *, user_id: uuid.UUID, monitor: Monitor, summary: dict,
) -> None:
    label = monitor.query_text or monitor.external_id or "monitor"
    session.add(InAppNotification(
        user_id=user_id, kind="discovery",
        subject_type="monitor", subject_id=monitor.id,
        payload={
            "monitor_label": label,
            "auto_ingested": summary["auto_ingested"],
            "pending_review": summary["pending_review"],
        },
        created_at=datetime.now(UTC),
    ))
    await session.flush()


async def process_candidates(
    session: AsyncSession, *, monitor: Monitor, candidates: list[Candidate],
) -> dict:
    summary = {"auto_ingested": 0, "pending_review": 0, "skipped_duplicate": 0}
    seen = await _existing_keys(session, monitor.id)
    auto_budget = monitor.per_poll_cap

    for c in candidates:
        key = (c.source_kind, c.external_id)
        if key in seen:
            summary["skipped_duplicate"] += 1
            continue
        seen.add(key)

        confidence = ("high" if monitor.kind == "entity"
                      else score_confidence(monitor.query_text or "",
                                            uploader=c.uploader, title=c.title))
        do_auto = confidence == "high" and auto_budget > 0
        url_rip_id = None
        if do_auto:
            url_rip_id = await _ingest_candidate(session, monitor=monitor, candidate=c)
            auto_budget -= 1
            status = "auto_ingested"
            summary["auto_ingested"] += 1
        else:
            status = "pending_review"
            summary["pending_review"] += 1

        session.add(MonitorDiscovery(
            monitor_id=monitor.id, source_kind=c.source_kind, external_id=c.external_id,
            title=c.title, uploader=c.uploader, webpage_url=c.webpage_url,
            duration_seconds=c.duration_seconds, thumbnail_url=c.thumbnail_url,
            confidence=confidence, status=status, url_rip_id=url_rip_id,
        ))
    await session.flush()

    if summary["auto_ingested"] or summary["pending_review"]:
        await _notify_owner(
            session, user_id=monitor.owner_user_id, monitor=monitor, summary=summary
        )
    return summary
