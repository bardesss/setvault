"""Admin REST endpoints for library refresh webhooks (§J15).

CRUD on the ``library_webhooks`` table plus a Test button that fires a
synthetic event so admins can verify their config without waiting for a
real set publish.
"""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from redis import Redis
from rq import Queue
from setvault_core.config import redis_url
from setvault_core.models.identity import User
from setvault_core.models.library_webhook import LibraryWebhook
from setvault_core.services.audit import log as audit_log
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_web.deps import current_user, db_session, require_admin

router = APIRouter(prefix="/api/admin/webhooks", tags=["admin"])


class WebhookCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    target_url: str = Field(min_length=1, max_length=2048)
    events: list[str] = Field(default_factory=list)
    body_template: dict | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True


class WebhookPatchIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    target_url: str | None = None
    events: list[str] | None = None
    body_template: dict | None = None
    headers: dict[str, str] | None = None
    enabled: bool | None = None


def _to_out(row: LibraryWebhook) -> dict:
    return {
        "id": str(row.id),
        "name": row.name,
        "target_url": row.target_url,
        "events": row.events,
        "body_template": row.body_template,
        "headers": row.headers,
        "enabled": row.enabled,
        "last_call_at": row.last_call_at.isoformat() if row.last_call_at else None,
        "last_status_code": row.last_status_code,
        "last_error": row.last_error,
    }


@router.get("")
async def list_webhooks(
    session: Annotated[AsyncSession, Depends(db_session)],
    _: Annotated[object, Depends(require_admin)],
):
    rows = (await session.execute(
        select(LibraryWebhook).order_by(LibraryWebhook.created_at)
    )).scalars().all()
    return {"items": [_to_out(r) for r in rows]}


@router.post("", status_code=201)
async def create_webhook(
    body: WebhookCreateIn,
    session: Annotated[AsyncSession, Depends(db_session)],
    admin: Annotated[User, Depends(current_user)],
    _: Annotated[object, Depends(require_admin)],
):
    row = LibraryWebhook(
        name=body.name,
        target_url=body.target_url,
        events=body.events,
        body_template=body.body_template,
        headers=body.headers,
        enabled=body.enabled,
    )
    session.add(row)
    await session.flush()
    await audit_log(
        session,
        actor_user_id=admin.id,
        action="webhook.added",
        target_type="LibraryWebhook",
        target_id=str(row.id),
        after={"name": row.name, "target_url": row.target_url},
    )
    await session.commit()
    return _to_out(row)


@router.patch("/{wh_id}")
async def update_webhook(
    wh_id: str,
    body: WebhookPatchIn,
    session: Annotated[AsyncSession, Depends(db_session)],
    admin: Annotated[User, Depends(current_user)],
    _: Annotated[object, Depends(require_admin)],
):
    try:
        row = await session.get(LibraryWebhook, uuid.UUID(wh_id))
    except ValueError as exc:
        raise HTTPException(status_code=404) from exc
    if row is None:
        raise HTTPException(status_code=404)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(row, field, value)
    await audit_log(
        session,
        actor_user_id=admin.id,
        action="webhook.updated",
        target_type="LibraryWebhook",
        target_id=str(row.id),
    )
    await session.commit()
    return _to_out(row)


@router.delete("/{wh_id}", status_code=204)
async def delete_webhook(
    wh_id: str,
    session: Annotated[AsyncSession, Depends(db_session)],
    admin: Annotated[User, Depends(current_user)],
    _: Annotated[object, Depends(require_admin)],
):
    try:
        row = await session.get(LibraryWebhook, uuid.UUID(wh_id))
    except ValueError as exc:
        raise HTTPException(status_code=404) from exc
    if row is None:
        raise HTTPException(status_code=404)
    await audit_log(
        session,
        actor_user_id=admin.id,
        action="webhook.deleted",
        target_type="LibraryWebhook",
        target_id=str(row.id),
    )
    await session.delete(row)
    await session.commit()


@router.post("/{wh_id}/test")
async def test_webhook(
    wh_id: str,
    session: Annotated[AsyncSession, Depends(db_session)],
    _: Annotated[object, Depends(require_admin)],
):
    """Enqueue an immediate dispatch with synthetic event data so admin can
    verify the endpoint without waiting for a real set publish."""
    try:
        row = await session.get(LibraryWebhook, uuid.UUID(wh_id))
    except ValueError as exc:
        raise HTTPException(status_code=404) from exc
    if row is None:
        raise HTTPException(status_code=404)
    redis = Redis.from_url(redis_url())
    Queue("default", connection=redis).enqueue(
        "setvault_core.jobs.webhook_dispatch.run_dispatch_webhook",
        webhook_id=str(row.id),
        event="webhook.test",
        set_slug="test-set-slug",
        set_id="00000000-0000-0000-0000-000000000000",
        title="(test event)",
    )
    return {"status": "queued"}
