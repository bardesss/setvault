from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from setvault_core.models.engagement_3c import InAppNotification
from setvault_core.models.identity import User
from setvault_core.schemas.notifications import (
    InAppNotificationOut,
    NotificationsListOut,
)
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_web.deps import current_user, db_session, parse_uuid

router = APIRouter(prefix="/api/me/notifications", tags=["notifications"])


def _to_out(n: InAppNotification) -> InAppNotificationOut:
    return InAppNotificationOut(
        id=str(n.id),
        kind=n.kind,
        subject_type=n.subject_type,
        subject_id=str(n.subject_id),
        payload=n.payload,
        read_at=n.read_at,
        created_at=n.created_at,
    )


@router.get("", response_model=NotificationsListOut)
async def list_notifications(
    user: Annotated[User, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(db_session)],
    unread: bool = False, limit: int = 50, offset: int = 0,
):
    q = select(InAppNotification).where(InAppNotification.user_id == user.id)
    if unread:
        q = q.where(InAppNotification.read_at.is_(None))
    q = q.order_by(InAppNotification.created_at.desc()).limit(limit).offset(offset)
    rows = (await session.execute(q)).scalars().all()
    unread_count = (await session.execute(
        select(func.count()).select_from(
            select(InAppNotification).where(
                InAppNotification.user_id == user.id,
                InAppNotification.read_at.is_(None),
            ).subquery()
        )
    )).scalar_one()
    return NotificationsListOut(
        items=[_to_out(n) for n in rows], unread_count=int(unread_count),
    )


@router.post("/{notification_id}/read", status_code=204)
async def mark_read(
    notification_id: str,
    user: Annotated[User, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    n = await session.get(InAppNotification, parse_uuid(notification_id))
    if n is None or n.user_id != user.id:
        raise HTTPException(status_code=404)
    if n.read_at is None:
        n.read_at = datetime.now(UTC)
        await session.commit()


@router.post("/read-all", status_code=204)
async def read_all(
    user: Annotated[User, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    await session.execute(
        update(InAppNotification)
        .where(InAppNotification.user_id == user.id,
               InAppNotification.read_at.is_(None))
        .values(read_at=datetime.now(UTC))
    )
    await session.commit()
