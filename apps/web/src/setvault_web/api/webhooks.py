"""Admin REST endpoints for library refresh webhooks (§J15).

CRUD on the ``library_webhooks`` table plus a Test button that fires a
synthetic event so admins can verify their config without waiting for a
real set publish. The signing secret is returned once (create / rotate);
header values are never returned, only their names.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Annotated
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from redis import Redis
from rq import Queue
from setvault_core.config import redis_url
from setvault_core.jobs.webhook_dispatch import enqueue_dispatch
from setvault_core.models.identity import User
from setvault_core.models.library_webhook import LibraryWebhook, WebhookDelivery
from setvault_core.services.audit import log as audit_log
from setvault_core.services.crypto import Crypter
from setvault_core.services.webhook_security import (
    KNOWN_EVENTS,
    generate_secret,
    get_headers,
    set_headers,
    set_secret,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_web.config import Settings, get_settings
from setvault_web.deps import current_user, db_session, parse_uuid, require_admin

router = APIRouter(prefix="/api/admin/webhooks", tags=["admin"])

_HEADER_NAME = re.compile(r"^[A-Za-z0-9-]{1,64}$")
_DELIVERIES_LIMIT = 50


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
    # name -> value replaces; "" or None deletes; an absent name keeps the stored value.
    headers: dict[str, str | None] | None = None
    enabled: bool | None = None


def _bad(detail: str) -> HTTPException:
    return HTTPException(status_code=400, detail=detail)


def _validate_events(events: list[str]) -> None:
    unknown = sorted(set(events) - set(KNOWN_EVENTS))
    if unknown:
        raise _bad(f"unknown events: {', '.join(unknown)}")


def _validate_url(url: str) -> None:
    try:
        parsed = urlparse(url)
        host = parsed.hostname
    except ValueError as exc:
        raise _bad("target_url is not a valid URL") from exc
    if parsed.scheme not in ("http", "https") or not host:
        raise _bad("target_url must be an http or https URL")


def _validate_header_names(names: Iterable[str]) -> None:
    for name in names:
        if not _HEADER_NAME.match(name):
            raise _bad("header names may only contain letters, digits and '-' (max 64)")


def _to_out(row: LibraryWebhook, crypter: Crypter) -> dict:
    return {
        "id": str(row.id),
        "name": row.name,
        "target_url": row.target_url,
        "events": row.events,
        "body_template": row.body_template,
        "header_names": sorted(get_headers(row, crypter)),
        "secret_set": row.encrypted_secret is not None,
        "enabled": row.enabled,
        "last_call_at": row.last_call_at.isoformat() if row.last_call_at else None,
        "last_status_code": row.last_status_code,
        "last_error": row.last_error,
    }


async def _get_or_404(session: AsyncSession, wh_id: str) -> LibraryWebhook:
    row = await session.get(LibraryWebhook, parse_uuid(wh_id))
    if row is None:
        raise HTTPException(status_code=404)
    return row


@router.get("")
async def list_webhooks(
    session: Annotated[AsyncSession, Depends(db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    _: Annotated[object, Depends(require_admin)],
):
    crypter = Crypter(settings.secret_key)
    rows = (await session.execute(
        select(LibraryWebhook).order_by(LibraryWebhook.created_at)
    )).scalars().all()
    return {"items": [_to_out(r, crypter) for r in rows]}


@router.post("", status_code=201)
async def create_webhook(
    body: WebhookCreateIn,
    session: Annotated[AsyncSession, Depends(db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    admin: Annotated[User, Depends(current_user)],
    _: Annotated[object, Depends(require_admin)],
):
    _validate_events(body.events)
    _validate_url(body.target_url)
    _validate_header_names(body.headers)
    crypter = Crypter(settings.secret_key)
    secret = generate_secret()
    row = LibraryWebhook(
        name=body.name,
        target_url=body.target_url,
        events=body.events,
        body_template=body.body_template,
        enabled=body.enabled,
    )
    set_secret(row, secret, crypter)
    set_headers(row, {k: v for k, v in body.headers.items() if v}, crypter)
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
    return _to_out(row, crypter) | {"secret": secret}


@router.patch("/{wh_id}")
async def update_webhook(
    wh_id: str,
    body: WebhookPatchIn,
    session: Annotated[AsyncSession, Depends(db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    admin: Annotated[User, Depends(current_user)],
    _: Annotated[object, Depends(require_admin)],
):
    row = await _get_or_404(session, wh_id)
    changes = body.model_dump(exclude_unset=True)
    if changes.get("events") is not None:
        _validate_events(changes["events"])
    if changes.get("target_url") is not None:
        _validate_url(changes["target_url"])
    header_changes = changes.pop("headers", None)
    if header_changes is not None:
        _validate_header_names(header_changes)
    crypter = Crypter(settings.secret_key)
    for field, value in changes.items():
        setattr(row, field, value)
    changed = sorted(changes)
    if header_changes is not None:
        merged = get_headers(row, crypter)
        for name, value in header_changes.items():
            if value:
                merged[name] = value
            else:
                merged.pop(name, None)
        set_headers(row, merged, crypter)
        changed = sorted([*changed, "headers"])
    await audit_log(
        session,
        actor_user_id=admin.id,
        action="webhook.updated",
        target_type="LibraryWebhook",
        target_id=str(row.id),
        after={"fields": changed},
    )
    await session.commit()
    return _to_out(row, crypter)


@router.post("/{wh_id}/rotate-secret")
async def rotate_secret(
    wh_id: str,
    session: Annotated[AsyncSession, Depends(db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    admin: Annotated[User, Depends(current_user)],
    _: Annotated[object, Depends(require_admin)],
):
    row = await _get_or_404(session, wh_id)
    secret = generate_secret()
    set_secret(row, secret, Crypter(settings.secret_key))
    await audit_log(
        session,
        actor_user_id=admin.id,
        action="webhook.secret_rotated",
        target_type="LibraryWebhook",
        target_id=str(row.id),
    )
    await session.commit()
    return {"secret": secret}


@router.get("/{wh_id}/deliveries")
async def list_deliveries(
    wh_id: str,
    session: Annotated[AsyncSession, Depends(db_session)],
    _: Annotated[object, Depends(require_admin)],
):
    row = await _get_or_404(session, wh_id)
    deliveries = (await session.execute(
        select(WebhookDelivery)
        .where(WebhookDelivery.webhook_id == row.id)
        .order_by(WebhookDelivery.created_at.desc())
        .limit(_DELIVERIES_LIMIT)
    )).scalars().all()
    return {"items": [
        {
            "delivery_id": d.delivery_id,
            "event": d.event,
            "attempt": d.attempt,
            "status_code": d.status_code,
            "error": d.error,
            "duration_ms": d.duration_ms,
            "created_at": d.created_at.isoformat(),
        }
        for d in deliveries
    ]}


@router.delete("/{wh_id}", status_code=204)
async def delete_webhook(
    wh_id: str,
    session: Annotated[AsyncSession, Depends(db_session)],
    admin: Annotated[User, Depends(current_user)],
    _: Annotated[object, Depends(require_admin)],
):
    row = await _get_or_404(session, wh_id)
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
    row = await _get_or_404(session, wh_id)
    delivery_id = enqueue_dispatch(
        Queue("default", connection=Redis.from_url(redis_url())),
        webhook_id=str(row.id),
        event="webhook.test",
        set_slug="test-set-slug",
        set_id="00000000-0000-0000-0000-000000000000",
        title="(test event)",
        retry=False,
    )
    return {"status": "queued", "delivery_id": delivery_id}
