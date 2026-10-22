"""Scheduled upgrade search and the per-set "search now" (Phase 7D §4.5 A).

Each hourly run takes the UPGRADE_SEARCH_BATCH sets that have gone longest
without a search (and sit below the quality cutoff), so a daily or weekly
sweep of a big library is spread across the window instead of bursting at the
sources. Per set it searches every enabled source one at a time through
``search_source`` (per-source rate limits), pre-filters the hits, and submits
at most one targeted upgrade rip. The rip pipeline then decides on the
measured audio (jobs/url_rip_job.py, services/set_upgrade.py).
"""
from __future__ import annotations

import logging
import os
import shutil
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

from setvault_ingest_sources.base import Candidate, SourceError
from setvault_ingest_sources.registry import get_source
from sqlalchemy import ColumnElement, and_, exists, func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_core.db import init_engine, run_job, session_factory
from setvault_core.models.catalog import LiveSet, MediaRoot, SetFingerprint
from setvault_core.models.identity import User
from setvault_core.models.upgrades import SetUpgradeEvent, already_tried
from setvault_core.models.url_rip import RipJob
from setvault_core.services.audio_match import MATCHER_VERSION
from setvault_core.services.ingest_sources import (
    SourceDisabledError,
    SourceRateLimitedError,
    list_states,
    search_source,
)
from setvault_core.services.monitor_match import score_confidence
from setvault_core.services.quality_profile import (
    QualityProfile,
    cutoff_unmet,
    effective_cutoff,
    get_profile,
    is_better,
    rank,
)
from setvault_core.services.set_upgrade import SEARCH_NOW_TRIGGER, upgrade_switches_on
from setvault_core.services.soundboard_hint import has_soundboard_hint
from setvault_core.services.system_config import get_config
from setvault_core.services.url_rip import DuplicateRipError, submit_rip

logger = logging.getLogger(__name__)

DATABASE_URL_ENV = "DATABASE_URL"

SCHEDULED_TRIGGER = "scheduled"
# Sets per hourly run: 20 x 168 runs covers ~3,300 sets a week (480 a day).
UPGRADE_SEARCH_BATCH = 20
# An upgrade briefly holds both copies (the old one sits in the recycle bin).
UPGRADE_MIN_FREE_BYTES = 5 * 1024**3
# A batch is up to 20 sets x every source, plus a yt-dlp probe per submit.
UPGRADE_SEARCH_JOB_TIMEOUT = 30 * 60
SEARCH_NOW_JOB_TIMEOUT = 10 * 60

_WINDOWS = {"daily": timedelta(hours=24), "weekly": timedelta(hours=168)}
Schedule = Literal["daily", "weekly", "off"]
DEFAULT_SCHEDULE: Schedule = "weekly"
_RESULTS_PER_SOURCE = 10
_DURATION_TOLERANCE = 0.10
_DURATION_MIN_SLACK_SECONDS = 120
# Each submit probes the URL with yt-dlp; a pick whose probe fails falls
# through to the next candidate, but only this many times per set. Picks that
# turn out already ripped (DuplicateRipError) don't count.
_MAX_SUBMIT_ATTEMPTS = 3
# The batch stops starting new sets after this long, so it ends well inside
# UPGRADE_SEARCH_JOB_TIMEOUT and doesn't hold the single worker for half an hour.
UPGRADE_SEARCH_BATCH_BUDGET_SECONDS = 20 * 60
# Same in-flight set as jobs/monitor_dispatch.py.
_IN_FLIGHT = {"queued", "started", "deferred", "scheduled"}
# R30: upgrade batches, "search now" and upgrade rips run on their own queue;
# the worker serves "default" first, so uploads and user rips never wait
# behind upgrade work.
UPGRADE_QUEUE = "low"
# The scheduled search submits no new rip while this many upgrade rips are
# queued or running, so a sweep can't fill the low queue with hours of
# downloads.
MAX_UPGRADE_RIPS_IN_FLIGHT = 2
# A rip started (or, still queued, created) longer ago than this is not
# running: RQ kills a rip at RIP_JOB_TIMEOUT (1 h) without the job marking
# itself failed; the extra hour covers the wait in the low queue. Measured
# from the start, not ``updated_at``: any later write to the row (a swap
# repointing it) bumps that without the rip being alive.
UPGRADE_RIP_STALE_AFTER = timedelta(hours=2)
_RIP_DONE = ("ready", "failed")

Outcome = Literal[
    "queued", "no_candidate", "rate_limited", "no_space", "not_eligible", "busy",
    "sources_failed",
]


class AllSourcesFailedError(Exception):
    """Every enabled source errored: nothing was actually searched."""


def normalize_schedule(value: str | None) -> Schedule:
    """The stored upgrade search schedule as the scheduler runs it. An
    unknown value (hand-edited, older build) is the column default, weekly,
    so the settings page and the scheduler agree; "off" stays off."""
    if value in ("daily", "weekly", "off"):
        return value  # type: ignore[return-value]
    return DEFAULT_SCHEDULE


def wanted_filter(profile: QualityProfile) -> ColumnElement[bool]:
    """Sets an upgrade search is for: published, live, upgrades on, a
    measured tier below the cutoff, and matchable (R28): a current-version
    raw fingerprint (without one every genuine candidate would be rejected
    as different audio) and not themselves a kept duplicate of another set.
    Shared by the scheduler (``due_sets``) and the admin Wanted list, so the
    list shows exactly what the schedule searches."""
    # cutoff_unmet() in SQL: a measured tier that isn't the cutoff or above.
    at_or_above = list(profile.order[: rank(profile, effective_cutoff(profile)) + 1])
    return and_(
        LiveSet.status == "published",
        LiveSet.deleted_at.is_(None),
        LiveSet.upgrades_enabled.is_(True),
        LiveSet.quality_tier.is_not(None),
        LiveSet.quality_tier.not_in(at_or_above),
        LiveSet.duplicate_of.is_(None),
        exists().where(
            SetFingerprint.live_set_id == LiveSet.id,
            SetFingerprint.raw.is_not(None),
            SetFingerprint.raw_version == MATCHER_VERSION,
        ),
    )


async def due_sets(
    session: AsyncSession, *, now: datetime, schedule: str | None, limit: int,
) -> list[LiveSet]:
    """Wanted sets (:func:`wanted_filter`) whose last search is older than
    the schedule window (:func:`normalize_schedule`). Never-searched first,
    then oldest."""
    window = _WINDOWS.get(normalize_schedule(schedule))
    if window is None or limit <= 0:
        return []
    if not (await get_config(session)).auto_upgrades_enabled:
        return []
    profile = await get_profile(session)
    stmt = (
        select(LiveSet)
        .where(
            wanted_filter(profile),
            or_(
                LiveSet.last_upgrade_search_at.is_(None),
                LiveSet.last_upgrade_search_at < now - window,
            ),
        )
        .order_by(
            LiveSet.last_upgrade_search_at.asc().nulls_first(),
            LiveSet.created_at, LiveSet.id,
        )
        .limit(limit)
    )
    return list((await session.execute(stmt)).unique().scalars())


def build_query(live: LiveSet) -> str:
    """Main artists + title (+ party), whitespace-normalized."""
    parts = [a.artist.name for a in live.artists if a.role == "main"]
    parts.append(live.title or "")
    if live.party is not None:
        parts.append(live.party.name)
    return " ".join(" ".join(parts).split())


def _duration_ok(live: LiveSet, c: Candidate) -> bool:
    # Unknown durations (Internet Archive search reports none) pass; the
    # fingerprint match on the download is what decides.
    if live.duration_seconds is None or c.duration_seconds is None:
        return True
    slack = max(live.duration_seconds * _DURATION_TOLERANCE, _DURATION_MIN_SLACK_SECONDS)
    return abs(c.duration_seconds - live.duration_seconds) <= slack


def pick_candidate(
    live: LiveSet,
    candidates: list[Candidate],
    *,
    profile: QualityProfile,
    tried: set[tuple[str, str]],
) -> Candidate | None:
    """The best plausible better copy, or None.

    Plausible: duration close, title/uploader matching the set's query, not
    tried before, and an expected tier that is unknown ("maybe") or strictly
    better. Known-better beats maybe, then tier rank, then the soundboard
    hint, then search order.

    Accepted (A4): lossless-first can pick a large original (an Internet
    Archive WAV); the rip is bounded by url_rip_job.MAX_DOWNLOAD_BYTES."""
    query = build_query(live)
    best: tuple[tuple[int, int, int, int], Candidate] | None = None
    for order, c in enumerate(candidates):
        if (c.source_kind, c.external_id) in tried or not _duration_ok(live, c):
            continue
        if score_confidence(query, uploader=c.uploader, title=c.title) != "high":
            continue
        known = c.expected_tier is not None
        if known and not is_better(
            profile, c.expected_tier, live.quality_tier,
            candidate_lossless=c.expected_tier == "lossless",
            current_lossless=live.audio_lossless,
        ):
            continue
        key = (
            0 if known else 1,
            rank(profile, c.expected_tier),
            0 if has_soundboard_hint(c.title) else 1,
            order,
        )
        if best is None or key < best[0]:
            best = (key, c)
    return best[1] if best else None


async def _enabled_kinds(session: AsyncSession) -> list[str]:
    return [
        st.kind for st in await list_states(session)
        if st.enabled and get_source(st.kind) is not None
    ]


async def _search(session: AsyncSession, query: str) -> list[Candidate]:
    """Every enabled source, one after another (no fan-out burst). A rate
    limit propagates: the caller stops and retries next run. So does an
    outage of every source (:class:`AllSourcesFailedError`)."""
    out: list[Candidate] = []
    searched = failed = 0
    for kind in await _enabled_kinds(session):
        try:
            out.extend(await search_source(
                session, kind=kind, query=query, limit=_RESULTS_PER_SOURCE,
            ))
            searched += 1
        except SourceDisabledError:
            continue
        except SourceError as e:
            # search_source already counted the failure against the source.
            failed += 1
            logger.warning("upgrade search: %s failed: %s", kind, e)
    if failed and not searched:
        raise AllSourcesFailedError(f"all {failed} sources failed")
    return out


async def _has_room(session: AsyncSession, live: LiveSet) -> bool:
    """Room for both copies: on the set's root and on the ingest root the
    rip downloads into (the swap moves the set there)."""
    root_ids = {live.media_root_id}
    ingest_id = (await session.execute(
        select(MediaRoot.id)
        .where(MediaRoot.default_for_ingest.is_(True), MediaRoot.enabled.is_(True))
        .order_by(MediaRoot.created_at).limit(1)
    )).scalar_one_or_none()
    if ingest_id is not None:
        root_ids.add(ingest_id)
    for root_id in root_ids:
        root = await session.get(MediaRoot, root_id)
        if root is None:
            continue
        try:
            free = shutil.disk_usage(root.host_path).free
        except OSError:
            return False
        if free < UPGRADE_MIN_FREE_BYTES:
            return False
    return True


async def _tried_keys(
    session: AsyncSession, live: LiveSet, candidates: list[Candidate],
) -> set[tuple[str, str]]:
    """Candidates not to download again: rejected before (upgrade history),
    already ripped for this set (a rip's external id can differ from the
    search's, so match on the URL too; failed rips count as well, or a
    Mixcloud candidate whose rip failed would be retried forever), or the
    set's own source."""
    prior_urls = set((await session.execute(
        select(RipJob.source_url).where(
            RipJob.upgrade_target_set_id == live.id,
        )
    )).scalars())
    tried: set[tuple[str, str]] = set()
    for c in candidates:
        key = (c.source_kind, c.external_id)
        if (
            c.webpage_url in prior_urls
            or (live.source_url is not None and c.webpage_url == live.source_url)
            or (live.source_external_id is not None
                and c.external_id == live.source_external_id)
            or await already_tried(
                session, live.id, source_kind=c.source_kind, external_id=c.external_id,
            )
        ):
            tried.add(key)
    return tried


async def _rip_owner(session: AsyncSession, live: LiveSet) -> uuid.UUID | None:
    """R20: the arrival inherits the rip's submitter, and only the set's
    owner (or an admin) may replace its audio."""
    if live.uploaded_by is not None:
        return live.uploaded_by
    return (await session.execute(
        select(User.id)
        .where(User.role == "admin", User.disabled_at.is_(None))
        .order_by(User.created_at).limit(1)
    )).scalar_one_or_none()


def _rejected_event(
    live: LiveSet, c: Candidate, reason: str, *, trigger: str,
) -> SetUpgradeEvent:
    return SetUpgradeEvent(
        live_set_id=live.id, trigger=trigger, outcome="rejected",
        reason=reason[:200],
        from_tier=live.quality_tier, from_codec=live.audio_codec,
        from_bitrate_kbps=live.audio_bitrate_kbps, from_source_type=live.source_type,
        from_source_url=live.source_url,
        to_source_url=c.webpage_url[:2048],
        candidate_source_kind=c.source_kind, candidate_external_id=c.external_id[:255],
    )


async def upgrade_rips_in_flight(session: AsyncSession, *, now: datetime) -> int:
    """Upgrade rips queued or running (any set), ignoring stale rows."""
    return int(await session.scalar(
        select(func.count()).select_from(RipJob).where(
            RipJob.upgrade_target_set_id.is_not(None),
            RipJob.status.not_in(_RIP_DONE),
            func.coalesce(RipJob.started_at, RipJob.created_at)
            >= now - UPGRADE_RIP_STALE_AFTER,
        )
    ) or 0)


def _enqueue_rip(rip_job_id: uuid.UUID) -> None:
    from redis import Redis
    from rq import Queue

    from setvault_core.jobs.url_rip_job import RIP_JOB_TIMEOUT

    redis = Redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
    Queue(UPGRADE_QUEUE, connection=redis).enqueue(
        "setvault_core.jobs.url_rip_job.run_rip_job", rip_job_id=str(rip_job_id),
        job_timeout=RIP_JOB_TIMEOUT,
    )


async def search_upgrade_for_set(
    session: AsyncSession,
    live_set_id: uuid.UUID,
    *,
    trigger: Literal["scheduled", "search_now"],
) -> Outcome:
    """Search the sources for a better copy of one set and submit at most one
    targeted upgrade rip. Commits. A rate limit, a full disk or (scheduled
    only) enough upgrade rips already in flight leaves the set unstamped so
    the next run retries it first."""
    live = await session.get(LiveSet, live_set_id)
    profile = await get_profile(session)
    if (
        live is None or live.deleted_at is not None or live.status != "published"
        or not cutoff_unmet(profile, live.quality_tier)
        or not await upgrade_switches_on(session, live, trigger=trigger)
    ):
        return "not_eligible"
    # Checked before searching so a full disk doesn't spend source budget.
    if not await _has_room(session, live):
        return "no_space"
    user_id = await _rip_owner(session, live)
    if user_id is None:
        return "not_eligible"
    # Checked before searching, so a busy queue doesn't spend source budget.
    # An explicit "search now" is one rip at most and not capped.
    if trigger == SCHEDULED_TRIGGER and (
        await upgrade_rips_in_flight(session, now=datetime.now(UTC))
        >= MAX_UPGRADE_RIPS_IN_FLIGHT
    ):
        return "busy"

    query = build_query(live)
    try:
        candidates = await _search(session, query) if query else []
    except SourceRateLimitedError as e:
        logger.info("upgrade search for set %s: %s rate-limited; retrying next run",
                    live.id, e)
        await session.commit()  # keep the source health updates
        return "rate_limited"
    except AllSourcesFailedError as e:
        # Not stamped, like a rate limit: an outage says nothing about
        # whether a better copy exists.
        logger.info("upgrade search for set %s: %s; retrying next run", live.id, e)
        await session.commit()  # keep the source health updates
        return "sources_failed"

    tried = await _tried_keys(session, live, candidates)
    now = datetime.now(UTC)
    failed_probes = 0
    while failed_probes < _MAX_SUBMIT_ATTEMPTS:
        pick = pick_candidate(live, candidates, profile=profile, tried=tried)
        if pick is None:
            break
        tried.add((pick.source_kind, pick.external_id))
        try:
            rip = await submit_rip(
                session, user_id=user_id, url=pick.webpage_url,
                upgrade_target_set_id=live.id, trigger=trigger,
            )
        except DuplicateRipError:
            # Already ripped (any set, any time): not a new copy. It doesn't
            # count against the cap, so a fresh lower-ranked pick is reached.
            # Accepted (A2): not recorded as rejected, since that other rip
            # may still succeed or fail (and then become retryable).
            continue
        except SQLAlchemyError:
            raise
        except Exception as exc:
            # Unsupported URL, probe failure (geo-blocked, private), playlist,
            # live stream. Record it so already_tried() skips it next sweep.
            failed_probes += 1
            logger.warning("upgrade search for set %s: submit failed for %s",
                           live.id, pick.webpage_url, exc_info=True)
            session.add(_rejected_event(live, pick, f"probe failed: {exc}", trigger=trigger))
            await session.flush()
            continue
        live.last_upgrade_search_at = now
        # Commit BEFORE enqueueing: a worker that can't see the RipJob row
        # yet drops it as "not found" (same as api/url_rip.py).
        await session.commit()
        try:
            _enqueue_rip(rip.id)
        except Exception:
            logger.exception("upgrade search: enqueue failed for rip %s", rip.id)
            rip.status = "failed"
            rip.error_text = "failed to enqueue worker"
            # Like any failed upgrade rip: a rejected event in the history.
            session.add(_rejected_event(live, pick, rip.error_text, trigger=trigger))
            await session.commit()
        return "queued"

    live.last_upgrade_search_at = now
    await session.commit()
    return "no_candidate"


def _clock() -> float:
    return time.monotonic()


async def _run_batch() -> dict:
    if DATABASE_URL_ENV in os.environ:
        init_engine(os.environ[DATABASE_URL_ENV])
    async with session_factory()() as s:
        config = await get_config(s)
        due = await due_sets(
            s, now=datetime.now(UTC), schedule=config.upgrade_search_schedule,
            limit=UPGRADE_SEARCH_BATCH,
        )
        ids = [live.id for live in due]
        await s.commit()

    summary: dict[str, int] = {"searched": 0}
    started = _clock()
    for set_id in ids:
        if _clock() - started >= UPGRADE_SEARCH_BATCH_BUDGET_SECONDS:
            # Out of time: the rest keep their place for the next run.
            summary["deferred"] = len(ids) - summary["searched"]
            break
        # One session per set, so one bad set can't poison the rest.
        async with session_factory()() as s:
            try:
                outcome: str = await search_upgrade_for_set(s, set_id, trigger=SCHEDULED_TRIGGER)
            except Exception:
                logger.exception("upgrade search failed for set %s", set_id)
                outcome = "error"
        if outcome == "error":
            # Stamp it anyway: a set that always fails must not be retried
            # (and hit the sources) every hour.
            async with session_factory()() as s:
                live = await s.get(LiveSet, set_id)
                if live is not None:
                    live.last_upgrade_search_at = datetime.now(UTC)
                    await s.commit()
        summary["searched"] += 1
        summary[outcome] = summary.get(outcome, 0) + 1
        if outcome in ("rate_limited", "busy", "sources_failed"):
            # The source budget is spent, the sources are down, or enough
            # upgrade rips are waiting: the rest keep their place for next hour.
            break
    return summary


def run_upgrade_search() -> dict:
    """RQ entry point (scheduled hourly)."""
    return run_job(_run_batch())


def run_search_upgrade_now(*, live_set_id: str) -> str:
    """RQ entry point for the per-set "search now" button."""
    async def _main() -> str:
        if DATABASE_URL_ENV in os.environ:
            init_engine(os.environ[DATABASE_URL_ENV])
        async with session_factory()() as s:
            return await search_upgrade_for_set(
                s, uuid.UUID(live_set_id), trigger=SEARCH_NOW_TRIGGER,
            )

    return run_job(_main())


def _search_now_job_id(live_set_id: uuid.UUID) -> str:
    return f"upgrade-search-now-{live_set_id}"


def enqueue_search_upgrade_now(live_set_id: uuid.UUID) -> bool:
    """Enqueue a "search now" unless one for this set is already in flight.
    Returns whether a job was enqueued."""
    from redis import Redis
    from rq import Queue
    from rq.job import Job

    redis = Redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
    job_id = _search_now_job_id(live_set_id)
    existing = Job.fetch_many([job_id], connection=redis)[0]
    if existing is not None and existing.get_status(refresh=True) in _IN_FLIGHT:
        return False
    Queue(UPGRADE_QUEUE, connection=redis).enqueue(
        "setvault_core.jobs.upgrade_search.run_search_upgrade_now",
        live_set_id=str(live_set_id), job_id=job_id, job_timeout=SEARCH_NOW_JOB_TIMEOUT,
    )
    return True
