from __future__ import annotations

import json
import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from setvault_core.models.identity import User
from setvault_core.models.system import NotificationConnector
from setvault_core.schemas.connector import (
    ConnectorCreateIn,
    ConnectorOut,
    ConnectorPatchIn,
    SmtpConfigOut,
    TestSendIn,
    TestSendOut,
)
from setvault_core.services.audit import log as audit_log
from setvault_core.services.crypto import Crypter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_web.config import Settings, get_settings
from setvault_web.deps import current_user, db_session, parse_uuid, require_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/connectors", tags=["admin"])


def _to_out(c: NotificationConnector, crypter: Crypter) -> ConnectorOut:
    config = json.loads(crypter.decrypt(c.encrypted_config).decode("utf-8"))
    return ConnectorOut(
        id=str(c.id), kind=c.kind, name=c.name, enabled=c.enabled,
        scope_filter=c.scope_filter,
        config=SmtpConfigOut(
            host=config["host"], port=config["port"], encryption=config["encryption"],
            username=config.get("username"),
            password_set=bool(config.get("password")),
            from_email=config["from_email"], from_name=config["from_name"],
            reply_to=config.get("reply_to"),
        ),
    )


@router.get("")
async def list_connectors(
    settings: Annotated[Settings, Depends(get_settings)],
    session: Annotated[AsyncSession, Depends(db_session)],
    _: Annotated[object, Depends(require_admin)],
):
    rows = (
        await session.execute(
            select(NotificationConnector).order_by(NotificationConnector.created_at)
        )
    ).scalars().all()
    crypter = Crypter(settings.secret_key)
    return {"items": [_to_out(r, crypter).model_dump() for r in rows]}


@router.post("", response_model=ConnectorOut, status_code=201)
async def create_connector(
    body: ConnectorCreateIn,
    settings: Annotated[Settings, Depends(get_settings)],
    session: Annotated[AsyncSession, Depends(db_session)],
    admin: Annotated[User, Depends(current_user)],
    _: Annotated[object, Depends(require_admin)],
):
    crypter = Crypter(settings.secret_key)
    blob = crypter.encrypt(body.config.model_dump_json().encode("utf-8"))
    row = NotificationConnector(
        kind=body.kind, name=body.name, encrypted_config=blob,
        scope_filter=body.scope_filter, enabled=body.enabled,
    )
    session.add(row)
    await session.flush()
    await audit_log(
        session,
        actor_user_id=admin.id,
        action="connector.created",
        target_type="NotificationConnector",
        target_id=str(row.id),
        after={"kind": body.kind, "name": body.name},
    )
    await session.commit()
    return _to_out(row, crypter)


@router.get("/{connector_id}", response_model=ConnectorOut)
async def show_connector(
    connector_id: str,
    settings: Annotated[Settings, Depends(get_settings)],
    session: Annotated[AsyncSession, Depends(db_session)],
    _: Annotated[object, Depends(require_admin)],
):
    row = await session.get(NotificationConnector, parse_uuid(connector_id))
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    return _to_out(row, Crypter(settings.secret_key))


def _audit_config(config: dict, fields) -> dict:
    """Config fields for an audit row; the password is only ever ``password_set``."""
    out = {f: config.get(f) for f in fields if f != "password"}
    if "password" in fields:
        out["password_set"] = bool(config.get("password"))
    return out


@router.patch("/{connector_id}", response_model=ConnectorOut)
async def patch_connector(
    connector_id: str,
    body: ConnectorPatchIn,
    settings: Annotated[Settings, Depends(get_settings)],
    session: Annotated[AsyncSession, Depends(db_session)],
    admin: Annotated[User, Depends(current_user)],
    _: Annotated[object, Depends(require_admin)],
):
    row = await session.get(NotificationConnector, parse_uuid(connector_id))
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    crypter = Crypter(settings.secret_key)
    old_config = json.loads(crypter.decrypt(row.encrypted_config).decode("utf-8"))
    new_config = dict(old_config)

    before: dict = {}
    after: dict = {}
    for field in ("name", "enabled"):
        if field in body.model_fields_set:
            before[field] = getattr(row, field)
            after[field] = getattr(body, field)

    if body.config is not None:
        patch = {f: getattr(body.config, f) for f in body.config.model_fields_set}
        # Blank password keeps the stored one; null clears it.
        if patch.get("password") == "":
            del patch["password"]
        new_config.update(patch)
        changed = [f for f in patch if new_config.get(f) != old_config.get(f)]
        if changed:
            before["config"] = _audit_config(old_config, changed)
            after["config"] = _audit_config(new_config, changed)
            # Whether a password exists is context for any config edit.
            before["config"].setdefault("password_set", bool(old_config.get("password")))
            after["config"].setdefault("password_set", bool(new_config.get("password")))

    for field in ("name", "enabled"):
        if field in after:
            setattr(row, field, after[field])
    row.encrypted_config = crypter.encrypt(json.dumps(new_config).encode("utf-8"))
    await audit_log(
        session,
        actor_user_id=admin.id,
        action="connector.edited",
        target_type="NotificationConnector",
        target_id=str(row.id),
        before=before,
        after=after,
    )
    await session.commit()
    return _to_out(row, crypter)


@router.delete("/{connector_id}", status_code=204)
async def delete_connector(
    connector_id: str,
    session: Annotated[AsyncSession, Depends(db_session)],
    admin: Annotated[User, Depends(current_user)],
    _: Annotated[object, Depends(require_admin)],
):
    row = await session.get(NotificationConnector, parse_uuid(connector_id))
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    await audit_log(
        session,
        actor_user_id=admin.id,
        action="connector.deleted",
        target_type="NotificationConnector",
        target_id=str(row.id),
        before={"kind": row.kind, "name": row.name},
    )
    await session.delete(row)
    await session.commit()


@router.post("/{connector_id}/test-send", response_model=TestSendOut)
async def test_send(
    connector_id: uuid.UUID,
    body: TestSendIn,
    settings: Annotated[Settings, Depends(get_settings)],
    session: Annotated[AsyncSession, Depends(db_session)],
    admin: Annotated[User, Depends(current_user)],
    _: Annotated[object, Depends(require_admin)],
):
    row = await session.get(NotificationConnector, connector_id)
    if row is None or row.kind != "smtp":
        raise HTTPException(status_code=404, detail="smtp connector not found")
    config = json.loads(
        Crypter(settings.secret_key).decrypt(row.encrypted_config).decode("utf-8")
    )
    await audit_log(
        session,
        actor_user_id=admin.id,
        action="connector.test_sent",
        target_type="NotificationConnector",
        target_id=str(row.id),
        after={"to": body.to, "dry_run": body.dry_run},
    )
    await session.commit()
    if body.dry_run:
        return TestSendOut(accepted=True, dry_run=True)
    try:
        # Implemented properly in Task D2 of Phase 2B; import is deferred so
        # this module remains importable until the email job lands.
        from setvault_core.jobs.email import send_email_sync
        send_email_sync(
            config=config, to=body.to,
            subject="SetVault test message",
            text="If you can read this, SMTP works.\n",
        )
        return TestSendOut(accepted=True, dry_run=False)
    except Exception as exc:
        logger.exception("SMTP test-send failed for connector %s", connector_id)
        error = f"{type(exc).__name__}: {exc}"
        for secret in (config.get("username"), config.get("password")):
            if secret:
                error = error.replace(secret, "***")
        return TestSendOut(accepted=False, dry_run=False, error=error)
