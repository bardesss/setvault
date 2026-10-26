from __future__ import annotations

import secrets as _secrets
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from pydantic import BaseModel
from setvault_core.models.identity import User
from setvault_core.services.passwords import hash_password, needs_rehash, verify_password
from setvault_core.services.sessions import SESSION_COOKIE, SESSION_TTL, SessionSigner
from setvault_core.services.single_user import single_user_auto_login_candidate
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_web.cookies import cookie_secure as _cookie_secure
from setvault_web.deps import current_user, db_session, get_signer, resolve_session_user
from setvault_web.middleware.csrf import CSRF_COOKIE
from setvault_web.rate_limit import enforce_auth_strict

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    id: str
    email: str
    username: str
    display_name: str
    role: str

    @classmethod
    def from_model(cls, u: User) -> UserOut:
        return cls(id=str(u.id), email=u.email, username=u.username,
                   display_name=u.display_name, role=u.role)


class LoginOut(BaseModel):
    user: UserOut


@router.post("/login", response_model=LoginOut, dependencies=[Depends(enforce_auth_strict)])
async def login(
    body: LoginIn,
    response: Response,
    session: Annotated[AsyncSession, Depends(db_session)],
    signer: Annotated[SessionSigner, Depends(get_signer)],
):
    result = await session.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()
    if (
        user is None
        or not user.password_hash
        or not verify_password(body.password, user.password_hash)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials",
        )
    if user.disabled_at is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="account disabled")
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)
        await session.commit()
    _issue_session(response, signer, user)
    return LoginOut(user=UserOut.from_model(user))


def _issue_session(response: Response, signer: SessionSigner, user: User) -> None:
    """Set the signed session cookie + a fresh CSRF cookie for ``user``. Shared
    by the password login and the single-user auto-login path."""
    secure = _cookie_secure()
    response.set_cookie(
        SESSION_COOKIE, signer.issue(str(user.id), user.session_version),
        httponly=True, secure=secure, samesite="lax",
        max_age=int(SESSION_TTL.total_seconds()), path="/",
    )
    response.set_cookie(
        CSRF_COOKIE, _secrets.token_urlsafe(32),
        httponly=False, secure=secure, samesite="lax", path="/",
    )


async def _user_from_session(
    session: AsyncSession, signer: SessionSigner, session_cookie: str | None,
) -> User | None:
    """Resolve the session user without raising (None when logged out)."""
    return await resolve_session_user(session, signer, session_cookie)


@router.post("/logout", status_code=204)
async def logout(response: Response, _: Annotated[User, Depends(current_user)]):
    response.delete_cookie(
        SESSION_COOKIE, path="/", secure=_cookie_secure(), httponly=True, samesite="lax",
    )


@router.get("/me", response_model=UserOut)
async def me(
    response: Response,
    session: Annotated[AsyncSession, Depends(db_session)],
    signer: Annotated[SessionSigner, Depends(get_signer)],
    session_cookie: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
):
    user = await _user_from_session(session, signer, session_cookie)
    if user is None:
        # Single-user auto-login: when enabled and exactly one active user
        # exists, transparently establish a session as that sole user so the
        # SPA never shows a login page.
        user = await single_user_auto_login_candidate(session)
        if user is not None:
            _issue_session(response, signer, user)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="not authenticated"
        )
    return UserOut.from_model(user)
