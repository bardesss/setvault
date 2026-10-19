from __future__ import annotations

import logging
import os
import re
import shutil
from typing import Annotated, get_args

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from setvault_core.models.api_token import ApiToken
from setvault_core.models.catalog import LiveSet, MediaRoot
from setvault_core.models.enrichment import ProviderConfig
from setvault_core.models.identity import User
from setvault_core.models.system import AuditEvent, NotificationConnector
from setvault_core.services.audit import log as audit_log
from setvault_core.services.system_config import get_config
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_web import __version__
from setvault_web.deps import current_user, db_session, require_admin
from setvault_web.schemas.settings import SettingsIn, SettingsOut

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])

_REDACT_SUFFIXES = ("_KEY", "_SECRET", "_TOKEN", "_PASSWORD", "_HOOK_SECRET")

# Scrub credentials embedded in URL-shaped env values (e.g. DATABASE_URL =
# postgresql://user:PASSWORD@host/db). The key name passes the suffix filter,
# so without this the password would be echoed in /api/admin/system.
_URL_CRED_RE = re.compile(r"(://[^:/?#@\s]+):([^@/?#\s]+)@")


def _scrub_url_creds(value: str) -> str:
    return _URL_CRED_RE.sub(r"\1:***@", value)


@router.get("/audit")
async def audit_list(
    session: Annotated[AsyncSession, Depends(db_session)],
    _: Annotated[object, Depends(require_admin)],
    action: str | None = None,
):
    stmt = select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(500)
    if action:
        stmt = stmt.where(AuditEvent.action == action)
    rows = (await session.execute(stmt)).scalars().all()
    return {
        "items": [
            {
                "id": str(e.id),
                "action": e.action,
                "actor_kind": e.actor_kind,
                "actor_user_id": str(e.actor_user_id) if e.actor_user_id else None,
                "target_type": e.target_type,
                "target_id": e.target_id,
                "before": e.before,
                "after": e.after,
                "created_at": e.created_at.isoformat(),
            }
            for e in rows
        ]
    }


@router.get("/system")
async def system_info(
    session: Annotated[AsyncSession, Depends(db_session)],
    _: Annotated[object, Depends(require_admin)],
):
    user_count = (await session.execute(select(func.count(User.id)))).scalar_one()
    set_count = (await session.execute(
        select(func.count(LiveSet.id)).where(LiveSet.deleted_at.is_(None))
    )).scalar_one()
    env = {
        k: _scrub_url_creds(v)
        for k, v in os.environ.items()
        if not any(k.upper().endswith(suf) for suf in _REDACT_SUFFIXES)
        and "PASS" not in k.upper()
        and "TOKEN" not in k.upper()
    }
    return {
        "version": __version__,
        "user_count": int(user_count),
        "set_count": int(set_count),
        "env": env,
    }


_SCHEDULES = get_args(SettingsOut.model_fields["upgrade_search_schedule"].annotation)


def _settings_out(config) -> SettingsOut:
    return SettingsOut(
        audit_retention_days=config.audit_retention_days,
        monitors_allow_all_users=config.monitors_allow_all_users,
        monitor_interval_seconds=config.monitor_interval_seconds,
        single_user_auto_login=config.single_user_auto_login,
        quality_tiers_order=list(config.quality_tiers_order),
        quality_cutoff=config.quality_cutoff,
        auto_upgrades_enabled=config.auto_upgrades_enabled,
        # An unknown stored value (hand-edited / older build) falls back to
        # the default instead of failing response validation with a 500.
        upgrade_search_schedule=(
            config.upgrade_search_schedule
            if config.upgrade_search_schedule in _SCHEDULES
            else "weekly"
        ),
    )


@router.get("/settings", response_model=SettingsOut)
async def get_settings(
    session: Annotated[AsyncSession, Depends(db_session)],
    _: Annotated[object, Depends(require_admin)],
) -> SettingsOut:
    """Editable app-wide settings backed by the SystemConfig singleton."""
    return _settings_out(await get_config(session))


@router.put("/settings", response_model=SettingsOut)
async def update_settings(
    body: SettingsIn,
    session: Annotated[AsyncSession, Depends(db_session)],
    _: Annotated[object, Depends(require_admin)],
) -> SettingsOut:
    config = await get_config(session)
    if body.audit_retention_days is not None:
        config.audit_retention_days = body.audit_retention_days
    if body.monitors_allow_all_users is not None:
        config.monitors_allow_all_users = body.monitors_allow_all_users
    if body.monitor_interval_seconds is not None:
        config.monitor_interval_seconds = body.monitor_interval_seconds
    if body.single_user_auto_login is not None:
        if body.single_user_auto_login:
            # Only offerable in the single-user case: enabling it on a
            # multi-user instance would silently drop auth for everyone.
            active = (await session.execute(
                select(func.count()).select_from(User).where(User.disabled_at.is_(None))
            )).scalar_one()
            if int(active) != 1:
                raise HTTPException(
                    status_code=422,
                    detail="single-user auto-login requires exactly one active user",
                )
        config.single_user_auto_login = body.single_user_auto_login
    if body.quality_tiers_order is not None:
        config.quality_tiers_order = body.quality_tiers_order
    if body.quality_cutoff is not None:
        config.quality_cutoff = body.quality_cutoff
    if body.auto_upgrades_enabled is not None:
        config.auto_upgrades_enabled = body.auto_upgrades_enabled
    if body.upgrade_search_schedule is not None:
        config.upgrade_search_schedule = body.upgrade_search_schedule
    await session.flush()
    await session.commit()
    return _settings_out(config)


@router.post("/maintenance/remeasure-loudness", status_code=202)
async def remeasure_loudness(
    session: Annotated[AsyncSession, Depends(db_session)],
    admin: Annotated[User, Depends(current_user)],
    _: Annotated[object, Depends(require_admin)],
):
    """Enqueue the one-off backfill that re-measures ``normalized_lufs`` for
    sets still holding the bogus ``-70.0`` from the old ebur128 parser.

    Returns 202 with the number of candidate sets; the scans run in the worker.
    """
    from redis import Redis
    from rq import Queue
    from setvault_core.jobs.loudness_backfill import BOGUS_LUFS

    candidates = (await session.execute(
        select(func.count()).select_from(LiveSet)
        .where(LiveSet.normalized_lufs == BOGUS_LUFS)
    )).scalar_one()
    redis = Redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
    rq_job = Queue("default", connection=redis).enqueue(
        "setvault_core.jobs.loudness_backfill.run_remeasure_bogus_loudness",
        job_timeout="6h",
    )
    await audit_log(
        session,
        actor_user_id=admin.id,
        action="maintenance.remeasure_loudness_requested",
        after={"candidates": int(candidates)},
    )
    await session.commit()
    return {"status": "queued", "job_id": rq_job.id, "candidates": int(candidates)}


@router.get("/maintenance/quality-backfill")
async def quality_backfill_candidates(
    session: Annotated[AsyncSession, Depends(db_session)],
    _: Annotated[object, Depends(require_admin)],
):
    """Dry run: how many sets still need a fingerprint and a quality reading,
    and how many duplicate pairs the cleanup would look at (published sets
    that are the same audio). Changes nothing."""
    from setvault_core.jobs.quality_backfill import (
        backfill_candidates,
        duplicate_pair_counts,
    )

    return {
        **await backfill_candidates(session),
        **await duplicate_pair_counts(session),
    }


class QualityBackfillIn(BaseModel):
    # Also merge published sets that turn out to be the same audio.
    cleanup: bool = False
    # Forget earlier failures so those sets are tried again.
    retry_failed: bool = False


@router.post("/maintenance/quality-backfill", status_code=202)
async def quality_backfill(
    response: Response,
    session: Annotated[AsyncSession, Depends(db_session)],
    admin: Annotated[User, Depends(current_user)],
    _: Annotated[object, Depends(require_admin)],
    body: QualityBackfillIn | None = None,
):
    """Enqueue the first slice of the fingerprint + quality backfill; each
    slice queues the next one until nothing is left. With ``cleanup`` the
    duplicate cleanup runs after it, also in slices; with ``retry_failed``
    the failure markers are cleared first. Only one run at a time: while one
    is queued or running this changes nothing and answers
    ``{"status": "already_running"}`` (200)."""
    from setvault_core.jobs import quality_backfill as qb

    if qb.quality_backfill_in_flight():
        response.status_code = 200
        return {"status": "already_running"}
    cleanup = bool(body and body.cleanup)
    retry_failed = bool(body and body.retry_failed)
    retried = await qb.clear_backfill_failures(session) if retry_failed else 0
    await qb.clear_stale_failures(session)
    await session.commit()
    candidates = await qb.backfill_candidates(session)
    rq_job = qb.start_quality_backfill(cleanup=cleanup)
    if rq_job is None:  # another request started one meanwhile
        response.status_code = 200
        return {"status": "already_running"}
    await audit_log(
        session,
        actor_user_id=admin.id,
        action="maintenance.quality_backfill_requested",
        after={**candidates, "cleanup": cleanup, "retried": retried},
    )
    await session.commit()
    return {"status": "queued", "job_id": rq_job.id, "cleanup": cleanup, **candidates}


def _disk_usage_for(host_path: str) -> dict | None:
    try:
        usage = shutil.disk_usage(host_path)
    except OSError:
        return None
    return {
        "free_bytes": int(usage.free),
        "used_bytes": int(usage.used),
        "total_bytes": int(usage.total),
    }


@router.get("/health")
async def health(
    session: Annotated[AsyncSession, Depends(db_session)],
    _: Annotated[object, Depends(require_admin)],
):
    """Consolidated admin health snapshot (§J11).

    Returns storage roots (with disk usage + last probe), notification
    connectors (with last delivery), API tokens (counts of expiring/expired),
    plus the cached GitHub release info from the daily poll.
    """
    storage_roots: list[dict] = []
    for r in (await session.execute(
        select(MediaRoot).order_by(MediaRoot.created_at)
    )).scalars():
        storage_roots.append({
            "id": str(r.id),
            "name": r.name,
            "host_path": r.host_path,
            "last_health_check_at": (
                r.last_health_check_at.isoformat() if r.last_health_check_at else None
            ),
            "last_health_status": r.last_health_status,
            "default_for_ingest": r.default_for_ingest,
            **(_disk_usage_for(r.host_path) or {}),
        })

    connectors: list[dict] = []
    for c in (await session.execute(
        select(NotificationConnector).order_by(NotificationConnector.created_at)
    )).scalars():
        connectors.append({
            "id": str(c.id),
            "name": c.name,
            "kind": c.kind,
            "enabled": c.enabled,
            "last_used_at": c.last_used_at.isoformat() if c.last_used_at else None,
            "last_status": c.last_status,
        })

    # API token counts. "Expired" + "expiring within 7 days" — we don't store
    # an expires_at on ApiToken right now (rss-scope tokens are revocable but
    # don't carry a TTL), so report active + revoked counts.
    token_total = (await session.execute(select(func.count(ApiToken.id)))).scalar_one()
    token_revoked = (await session.execute(
        select(func.count(ApiToken.id)).where(ApiToken.revoked_at.is_not(None))
    )).scalar_one()

    # Configured providers — kind, enabled, priority. Error-rate tracking is
    # deferred to v0.1.1 (we don't currently log provider outcomes anywhere
    # queryable; the response-cache table is for cache, not telemetry).
    providers: list[dict] = []
    for p in (await session.execute(
        select(ProviderConfig).order_by(ProviderConfig.priority)
    )).scalars():
        providers.append({
            "kind": p.provider_kind,
            "name": p.name,
            "enabled": p.enabled,
            "priority": p.priority,
        })

    config = await get_config(session)
    is_outdated = (
        config.latest_release_version is not None
        and config.latest_release_version.lstrip("v") != __version__.lstrip("v")
    )

    return {
        "version": {
            "current": __version__,
            "latest_known": config.latest_release_version,
            "latest_release_url": config.latest_release_url,
            "latest_checked_at": (
                config.latest_release_checked_at.isoformat()
                if config.latest_release_checked_at else None
            ),
            "is_outdated": bool(is_outdated),
        },
        "audit_retention_days": config.audit_retention_days,
        "monitors_allow_all_users": config.monitors_allow_all_users,
        "monitor_interval_seconds": config.monitor_interval_seconds,
        "storage_roots": storage_roots,
        "connectors": connectors,
        "providers": providers,
        "tokens": {
            "total": int(token_total),
            "revoked": int(token_revoked),
            "active": int(token_total) - int(token_revoked),
        },
    }
