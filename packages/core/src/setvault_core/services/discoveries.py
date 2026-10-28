"""Turn a monitor's search candidates into discovery rows + notifications.

Per candidate: skip if already a discovery for this monitor; else score
confidence (entity monitors are always high), auto-ingest high-confidence
candidates up to the monitor's per_poll_cap (rest -> pending_review), and write
one `discovery` InAppNotification summarizing the poll.
"""
from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from setvault_ingest_sources.base import Candidate
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_core import triggers
from setvault_core.models.engagement_3c import InAppNotification
from setvault_core.models.monitors import Monitor, MonitorDiscovery
from setvault_core.models.url_rip import RipJob
from setvault_core.services.monitor_match import score_confidence
from setvault_core.services.quality_profile import QualityProfile, get_profile, rank
from setvault_core.services.soundboard_hint import (
    has_soundboard_hint,
    strip_soundboard_terms,
)

logger = logging.getLogger(__name__)


async def _existing_keys(session: AsyncSession, monitor_id: uuid.UUID) -> set[tuple[str, str]]:
    rows = (await session.execute(
        select(MonitorDiscovery.source_kind, MonitorDiscovery.external_id)
        .where(MonitorDiscovery.monitor_id == monitor_id)
    )).all()
    return {(r[0], r[1]) for r in rows}


async def _ingest_candidate(
    session: AsyncSession, *, monitor: Monitor, candidate: Candidate,
) -> tuple[RipJob, bool] | None:
    """Submit the candidate's webpage_url through the url-rip pipeline WITHOUT
    enqueueing: the poll has not committed yet, so a worker could not see the
    RipJob. Returns ``(job, is_new)`` (``is_new`` False for an already-running
    duplicate, which must not be enqueued again), or None if the submit failed."""
    from setvault_core.services.url_rip import DuplicateRipError, submit_rip

    try:
        job = await submit_rip(
            session, user_id=monitor.owner_user_id, url=candidate.webpage_url,
            trigger=triggers.MONITOR,
        )
    except DuplicateRipError as e:
        return e.existing, False
    except Exception:
        logger.exception(
            "monitor %s: auto-ingest failed for %s", monitor.id, candidate.webpage_url,
        )
        return None
    return job, True


async def _notify_owner(
    session: AsyncSession, *, user_id: uuid.UUID, monitor: Monitor, summary: dict,
) -> InAppNotification:
    label = monitor.query_text or monitor.external_id or "monitor"
    notification = InAppNotification(
        user_id=user_id, kind="discovery",
        subject_type="monitor", subject_id=monitor.id,
        payload={
            "monitor_label": label,
            "auto_ingested": summary["auto_ingested"],
            "pending_review": summary["pending_review"],
        },
        created_at=datetime.now(UTC),
    )
    session.add(notification)
    await session.flush()
    return notification


async def revert_failed_auto_ingest(
    session: AsyncSession, *, failed_job_ids: list[uuid.UUID],
    notification: InAppNotification | None,
) -> int:
    """After a failed enqueue: put those auto-ingested discoveries back up for
    review and correct the owner's notification counts. Returns the number moved."""
    if not failed_job_ids:
        return 0
    rows = (
        await session.execute(
            select(MonitorDiscovery).where(
                MonitorDiscovery.url_rip_id.in_(failed_job_ids),
                MonitorDiscovery.status == "auto_ingested",
            )
        )
    ).scalars().all()
    for d in rows:
        d.status = "pending_review"
        d.url_rip_id = None
    if rows and notification is not None:
        payload = dict(notification.payload)
        payload["auto_ingested"] = max(0, payload.get("auto_ingested", 0) - len(rows))
        payload["pending_review"] = payload.get("pending_review", 0) + len(rows)
        notification.payload = payload
    await session.flush()
    return len(rows)


def _same_set(a: Candidate, b: Candidate) -> bool:
    """Same set = titles match by score_confidence both ways (soundboard
    keywords ignored) and durations within +-10%.

    A candidate without a duration is never "the same set" as another, so it
    forms its own group and is never dropped as a worse copy (we can't tell).
    The duration rule also keeps the same title from different nights (a
    festival set played every year) apart once their lengths differ."""
    ta, tb = strip_soundboard_terms(a.title), strip_soundboard_terms(b.title)
    if not (a.duration_seconds and b.duration_seconds):
        return False
    if abs(a.duration_seconds - b.duration_seconds) > 0.1 * max(
        a.duration_seconds, b.duration_seconds
    ):
        return False
    return (
        score_confidence(ta, uploader=None, title=tb) == "high"
        and score_confidence(tb, uploader=None, title=ta) == "high"
    )


def _best_copies(
    profile: QualityProfile, items: list[tuple[Candidate, str]],
) -> set[int]:
    """Indexes (into ``items``) of the best high-confidence copy per same-set
    group. Best = lowest rank (unknown last), then soundboard hint, then first."""
    groups: list[list[int]] = []
    for i, (c, conf) in enumerate(items):
        if conf != "high":
            continue
        for g in groups:
            if _same_set(items[g[0]][0], c):
                g.append(i)
                break
        else:
            groups.append([i])
    return {
        min(g, key=lambda i: (rank(profile, items[i][0].expected_tier),
                              not has_soundboard_hint(items[i][0].title), i))
        for g in groups
    }


async def process_candidates(
    session: AsyncSession, *, monitor: Monitor, candidates: list[Candidate],
) -> dict:
    summary = {"auto_ingested": 0, "pending_review": 0, "skipped_duplicate": 0}
    seen = await _existing_keys(session, monitor.id)
    auto_budget = monitor.per_poll_cap
    new_jobs: list[RipJob] = []

    fresh: list[tuple[Candidate, str]] = []
    for c in candidates:
        key = (c.source_kind, c.external_id)
        if key in seen:
            summary["skipped_duplicate"] += 1
            continue
        seen.add(key)
        confidence = ("high" if monitor.kind == "entity"
                      else score_confidence(monitor.query_text or "",
                                            uploader=c.uploader, title=c.title))
        fresh.append((c, confidence))
    # Several copies of one set in a poll: only the best may use the auto budget.
    best = _best_copies(await get_profile(session), fresh)

    for i, (c, confidence) in enumerate(fresh):
        do_auto = confidence == "high" and i in best and auto_budget > 0
        url_rip_id = None
        status = "pending_review"
        if do_auto:
            ingested = await _ingest_candidate(session, monitor=monitor, candidate=c)
            if ingested is not None:
                job, is_new = ingested
                url_rip_id = job.id
                if is_new:
                    new_jobs.append(job)
                auto_budget -= 1
                status = "auto_ingested"
        if status == "auto_ingested":
            summary["auto_ingested"] += 1
        else:
            # Includes a failed submit: reviewable, no budget spent.
            summary["pending_review"] += 1

        session.add(MonitorDiscovery(
            monitor_id=monitor.id, source_kind=c.source_kind, external_id=c.external_id,
            title=c.title, uploader=c.uploader, webpage_url=c.webpage_url,
            duration_seconds=c.duration_seconds, thumbnail_url=c.thumbnail_url,
            confidence=confidence, status=status, url_rip_id=url_rip_id,
        ))
    await session.flush()

    notification = None
    if summary["auto_ingested"] or summary["pending_review"]:
        notification = await _notify_owner(
            session, user_id=monitor.owner_user_id, monitor=monitor, summary=summary
        )
    # Handed to poll_monitor, which commits and then enqueues them (and fixes
    # up the notification if an enqueue fails).
    summary["rip_jobs"] = new_jobs
    summary["notification"] = notification
    return summary
