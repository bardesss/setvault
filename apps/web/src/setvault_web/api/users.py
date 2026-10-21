from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from setvault_core.models.identity import User
from setvault_core.services.audit import log as audit_log
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_web.deps import current_user, db_session, require_admin

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("")
async def list_users(
    session: Annotated[AsyncSession, Depends(db_session)],
    _: Annotated[object, Depends(require_admin)],
):
    rows = (
        await session.execute(select(User).order_by(User.created_at))
    ).scalars().all()
    return {
        "items": [
            {
                "id": str(u.id),
                "email": u.email,
                "username": u.username,
                "display_name": u.display_name,
                "role": u.role,
                "disabled_at": u.disabled_at.isoformat() if u.disabled_at else None,
            }
            for u in rows
        ]
    }


@router.post("/{user_id}/disable", status_code=204)
async def disable_user(
    user_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(db_session)],
    admin: Annotated[User, Depends(current_user)],
    _: Annotated[object, Depends(require_admin)],
):
    target = await session.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="not found")
    target.disabled_at = datetime.now(UTC)
    target.session_version += 1
    await audit_log(
        session,
        actor_user_id=admin.id,
        action="user.disabled",
        target_type="User",
        target_id=str(target.id),
    )
    await session.commit()
