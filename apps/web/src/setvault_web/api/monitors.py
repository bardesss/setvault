from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from setvault_core import triggers
from setvault_core.models.identity import User
from setvault_core.models.monitors import Monitor, MonitorDiscovery
from setvault_core.schemas.monitors import (
    DiscoveriesListOut,
    DiscoveryOut,
    MonitorCreate,
    MonitorOut,
    MonitorsListOut,
    MonitorUpdate,
)
from setvault_core.services import monitors as svc
from setvault_core.services.audit import log as audit_log
from setvault_core.services.rip_enqueue import enqueue_rip
from setvault_core.services.url_rip import DuplicateRipError, submit_rip
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_web.api.images import build_proxied_image_url
from setvault_web.deps import db_session, parse_uuid, require_can_monitor

logger = logging.getLogger(__name__)

router = APIRouter(tags=["monitors"])


def _owner_scope(user: User) -> uuid.UUID | None:
    """Owner filter for a request: ``None`` for admins (see/act on all), else
    the user's own id so non-admins are confined to their own monitors."""
    return None if user.role == "admin" else user.id


def _monitor_out(m: Monitor, refs: dict) -> MonitorOut:
    name, slug = refs.get((m.catalog_kind, m.catalog_id), (None, None))
    return MonitorOut(
        id=str(m.id),
        kind=m.kind,
        query_text=m.query_text,
        source_kind=m.source_kind,
        external_id=m.external_id,
        enabled=m.enabled,
        per_poll_cap=m.per_poll_cap,
        last_checked_at=m.last_checked_at,
        created_at=m.created_at,
        catalog_kind=m.catalog_kind,
        catalog_id=str(m.catalog_id) if m.catalog_id else None,
        catalog_name=name,
        catalog_slug=slug,
    )


async def _monitors_out(session: AsyncSession, monitors: list[Monitor]) -> list[MonitorOut]:
    refs = await svc.catalog_refs(session, monitors)
    return [_monitor_out(m, refs) for m in monitors]


async def _audit(session: AsyncSession, user: User, action: str, m_id, **kw) -> None:
    await audit_log(session, actor_user_id=user.id, action=action,
                    target_type="Monitor", target_id=str(m_id), **kw)


@router.post("/api/monitors", response_model=MonitorOut, status_code=201)
async def create_monitor(
    payload: MonitorCreate,
    response: Response,
    user: Annotated[User, Depends(require_can_monitor)],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    catalog_id = (parse_uuid(payload.catalog_id, status_code=422, detail="invalid catalog_id")
                  if payload.catalog_id is not None else None)
    if payload.catalog_kind is not None:
        try:
            await svc.check_catalog_link(session, payload.kind, payload.catalog_kind, catalog_id)
        except svc.CatalogLinkError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        # One linked monitor per (owner, entity): a repeat create re-enables it.
        await svc.lock_catalog_link(session, user.id, payload.catalog_kind, catalog_id)
        existing = await svc.find_catalog_monitor(
            session, owner_user_id=user.id, catalog_kind=payload.catalog_kind,
            catalog_id=catalog_id,
        )
        if existing is not None:
            if not existing.enabled:
                existing.enabled = True
                await _audit(session, user, "monitor.edited", existing.id,
                             before={"enabled": False}, after={"enabled": True})
            await session.commit()
            response.status_code = 200
            return (await _monitors_out(session, [existing]))[0]
    try:
        m = await svc.create_monitor(
            session,
            owner_user_id=user.id,
            kind=payload.kind,
            query_text=payload.query_text,
            source_kind=payload.source_kind,
            external_id=payload.external_id,
            per_poll_cap=payload.per_poll_cap,
            catalog_kind=payload.catalog_kind,
            catalog_id=catalog_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await _audit(session, user, "monitor.created", m.id, after=svc.audit_fields(m))
    await session.commit()
    return (await _monitors_out(session, [m]))[0]


@router.get("/api/monitors", response_model=MonitorsListOut)
async def list_monitors(
    user: Annotated[User, Depends(require_can_monitor)],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    rows = await svc.list_monitors(session, owner_user_id=_owner_scope(user))
    return MonitorsListOut(items=await _monitors_out(session, rows))


@router.put("/api/monitors/{monitor_id}", response_model=MonitorOut)
async def update_monitor(
    monitor_id: str,
    payload: MonitorUpdate,
    user: Annotated[User, Depends(require_can_monitor)],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    try:
        result = await svc.update_monitor(
            session, parse_uuid(monitor_id), payload.model_dump(exclude_unset=True),
            owner_user_id=_owner_scope(user),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404)
    m, before, after = result
    if after:
        await _audit(session, user, "monitor.edited", m.id, before=before, after=after)
    await session.commit()
    return (await _monitors_out(session, [m]))[0]


@router.delete("/api/monitors/{monitor_id}", status_code=204)
async def delete_monitor(
    monitor_id: str,
    user: Annotated[User, Depends(require_can_monitor)],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    mid = parse_uuid(monitor_id)
    before = await svc.delete_monitor(session, mid, owner_user_id=_owner_scope(user))
    if before is None:
        raise HTTPException(status_code=404)
    await _audit(session, user, "monitor.deleted", mid, before=before)
    await session.commit()


def _disc_out(d: MonitorDiscovery) -> DiscoveryOut:
    return DiscoveryOut(
        id=str(d.id),
        monitor_id=str(d.monitor_id),
        source_kind=d.source_kind,
        external_id=d.external_id,
        title=d.title,
        uploader=d.uploader,
        webpage_url=d.webpage_url,
        duration_seconds=d.duration_seconds,
        thumbnail_url=build_proxied_image_url(d.thumbnail_url),
        confidence=d.confidence,
        status=d.status,
        created_at=d.created_at,
    )


async def _owned_discovery_or_404(
    session: AsyncSession, user: User, discovery_id: str,
) -> MonitorDiscovery:
    """Load a discovery, enforcing ownership for non-admins. 404 (not 403) when
    the row is missing or owned by another user, so callers can't probe ids."""
    d = await session.get(MonitorDiscovery, parse_uuid(discovery_id))
    if d is None:
        raise HTTPException(status_code=404)
    scope = _owner_scope(user)
    if scope is not None:
        m = await session.get(Monitor, d.monitor_id)
        if m is None or m.owner_user_id != scope:
            raise HTTPException(status_code=404)
    return d


@router.get("/api/me/discoveries", response_model=DiscoveriesListOut)
async def list_discoveries(
    user: Annotated[User, Depends(require_can_monitor)],
    session: Annotated[AsyncSession, Depends(db_session)],
    status: Annotated[list[str] | None, Query()] = None,
):
    q = select(MonitorDiscovery).order_by(MonitorDiscovery.created_at.desc())
    pending = select(func.count()).select_from(MonitorDiscovery).where(
        MonitorDiscovery.status == "pending_review",
    )
    scope = _owner_scope(user)
    if scope is not None:
        q = q.join(Monitor, Monitor.id == MonitorDiscovery.monitor_id).where(
            Monitor.owner_user_id == scope,
        )
        pending = pending.join(Monitor, Monitor.id == MonitorDiscovery.monitor_id).where(
            Monitor.owner_user_id == scope,
        )
    if status:
        q = q.where(MonitorDiscovery.status.in_(status))
    rows = (await session.execute(q.limit(200))).scalars().all()
    return DiscoveriesListOut(
        items=[_disc_out(d) for d in rows],
        pending_count=(await session.execute(pending)).scalar_one(),
    )


@router.post("/api/me/discoveries/{discovery_id}/rip", status_code=204)
async def rip_discovery(
    discovery_id: str,
    user: Annotated[User, Depends(require_can_monitor)],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    d = await _owned_discovery_or_404(session, user, discovery_id)
    if d.status != "pending_review":
        return
    try:
        job = await submit_rip(
            session, user_id=user.id, url=d.webpage_url, trigger=triggers.MONITOR,
        )
    except DuplicateRipError as exc:
        d.url_rip_id = exc.existing.id
        d.status = "ingested"
        d.decided_at = datetime.now(UTC)
        await session.commit()
        return
    d.url_rip_id = job.id
    # enqueue_rip commits the RipJob and the discovery's link before enqueueing.
    # If the enqueue fails the job is left failed (visible in Downloads) and the
    # discovery stays pending_review so it can be accepted again.
    if await enqueue_rip(session, job):
        d.status = "ingested"
        d.decided_at = datetime.now(UTC)
        await session.commit()


@router.post("/api/me/discoveries/{discovery_id}/dismiss", status_code=204)
async def dismiss_discovery(
    discovery_id: str,
    user: Annotated[User, Depends(require_can_monitor)],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    d = await _owned_discovery_or_404(session, user, discovery_id)
    d.status = "dismissed"
    d.decided_at = datetime.now(UTC)
    await session.commit()
