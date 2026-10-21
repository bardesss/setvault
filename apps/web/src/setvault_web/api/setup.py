from __future__ import annotations

import secrets as _secrets
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from setvault_core.models.identity import User
from setvault_core.services.sessions import SESSION_COOKIE, SESSION_TTL, SessionSigner
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_web.api.auth import UserOut
from setvault_web.cookies import cookie_secure as _cookie_secure
from setvault_web.create_admin import CreateAdminError, create_or_promote_admin
from setvault_web.deps import db_session, get_signer
from setvault_web.middleware.csrf import CSRF_COOKIE
from setvault_web.rate_limit import enforce_auth_strict

router = APIRouter(prefix="/api/setup", tags=["setup"])


class SetupStatusOut(BaseModel):
    needs_setup: bool


class SetupIn(BaseModel):
    email: str
    password: str
    display_name: str | None = None


async def _user_count(session: AsyncSession) -> int:
    return int(
        (await session.execute(select(func.count()).select_from(User))).scalar_one()
    )


@router.get("/status", response_model=SetupStatusOut)
async def setup_status(
    session: Annotated[AsyncSession, Depends(db_session)],
) -> SetupStatusOut:
    return SetupStatusOut(needs_setup=(await _user_count(session)) == 0)


@router.post("", response_model=UserOut, dependencies=[Depends(enforce_auth_strict)])
async def create_first_admin(
    body: SetupIn,
    response: Response,
    session: Annotated[AsyncSession, Depends(db_session)],
    signer: Annotated[SessionSigner, Depends(get_signer)],
) -> UserOut:
    # Serialize concurrent first-admin submits on a fresh DB; the txn-scoped
    # advisory lock auto-releases at commit (mirrors dev_seed.py). Constant is an
    # arbitrary stable u32 unique to setup.
    await session.execute(text("SELECT pg_advisory_xact_lock(0x5e7c0de1)"))
    if (await _user_count(session)) > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="setup already complete"
        )
    try:
        user, _action = await create_or_promote_admin(
            session, body.email, body.password, display_name=body.display_name
        )
    except CreateAdminError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    cookie = signer.issue(str(user.id), user.session_version)
    secure = _cookie_secure()
    response.set_cookie(
        SESSION_COOKIE, cookie,
        httponly=True, secure=secure, samesite="lax",
        max_age=int(SESSION_TTL.total_seconds()), path="/",
    )
    response.set_cookie(
        CSRF_COOKIE, _secrets.token_urlsafe(32),
        httponly=False, secure=secure, samesite="lax", path="/",
    )
    return UserOut.from_model(user)
