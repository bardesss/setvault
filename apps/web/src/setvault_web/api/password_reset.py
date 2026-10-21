from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from setvault_core.models.identity import EmailToken, User
from setvault_core.services.password_policy import MIN_PASSWORD_LENGTH
from setvault_core.services.passwords import hash_password
from setvault_core.services.tokens import expires, generate_token, hash_token, now_utc
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_web.config import Settings, get_settings
from setvault_web.deps import db_session, require_admin
from setvault_web.rate_limit import enforce_auth_strict
from setvault_web.services.notifications import enqueue_email

router = APIRouter(prefix="/api/password-reset", tags=["auth"])


# `email: str` (not EmailStr) per C2/C4 precedent — login lookup,
# no benefit to format validation; email-validator also rejects `.test` TLD.
class RequestIn(BaseModel):
    email: str


@router.post("/request", status_code=204, dependencies=[Depends(enforce_auth_strict)])
async def request_reset(
    body: RequestIn,
    settings: Annotated[Settings, Depends(get_settings)],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    user = (await session.execute(
        select(User).where(User.email == body.email)
    )).scalar_one_or_none()
    if user is None:
        return  # silent: no email leak
    plaintext, digest = generate_token()
    token = EmailToken(user_id=user.id, email=user.email, kind="password_reset",
                       token_hash=digest, payload={}, expires_at=expires(1))
    session.add(token)
    await session.commit()

    link = f"{settings.base_url}/reset/{plaintext}"
    await enqueue_email(
        session,
        settings,
        to=user.email,
        subject="SetVault password reset",
        text=f"Open this link to reset your password (expires in 1 hour):\n\n{link}\n",
    )


class AdminLinkIn(BaseModel):
    email: str


class AdminLinkOut(BaseModel):
    reset_link: str
    expires_at: datetime


@router.post("/admin-link", response_model=AdminLinkOut)
async def admin_link(
    body: AdminLinkIn,
    settings: Annotated[Settings, Depends(get_settings)],
    session: Annotated[AsyncSession, Depends(db_session)],
    _: Annotated[User, Depends(require_admin)],
):
    user = (await session.execute(
        select(User).where(User.email == body.email)
    )).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    plaintext, digest = generate_token()
    token = EmailToken(user_id=user.id, email=user.email, kind="password_reset",
                       token_hash=digest, payload={}, expires_at=expires(1))
    session.add(token)
    await session.commit()
    return AdminLinkOut(reset_link=f"{settings.base_url}/reset/{plaintext}",
                        expires_at=token.expires_at)


class RedeemIn(BaseModel):
    password: str = Field(min_length=MIN_PASSWORD_LENGTH)


@router.post("/{token}/redeem", status_code=204,
             dependencies=[Depends(enforce_auth_strict)])
async def redeem(token: str, body: RedeemIn,
                 session: Annotated[AsyncSession, Depends(db_session)]):
    digest = hash_token(token)
    row = (await session.execute(
        select(EmailToken).where(
            EmailToken.token_hash == digest, EmailToken.kind == "password_reset"
        )
    )).scalar_one_or_none()
    if row is None or row.used_at is not None or (row.expires_at and row.expires_at < now_utc()):
        raise HTTPException(status_code=410, detail="reset link invalid or expired")
    user = await session.get(User, row.user_id)
    if user is None:
        raise HTTPException(status_code=410, detail="user no longer exists")
    user.password_hash = hash_password(body.password)
    row.used_at = datetime.now(UTC)
    await session.commit()
