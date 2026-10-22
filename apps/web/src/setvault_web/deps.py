from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, status
from setvault_core.db import session_factory
from setvault_core.models.identity import User
from setvault_core.services.sessions import SESSION_COOKIE, SessionSigner
from setvault_core.services.system_config import get_config
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_web.config import Settings, get_settings


def parse_uuid(
    value: str, *, status_code: int = 404, detail: str = "not found",
) -> uuid.UUID:
    """Parse a client-supplied id; a malformed one is a clean 4xx, never a 500."""
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError, TypeError) as exc:
        raise HTTPException(status_code=status_code, detail=detail) from exc


def get_signer(settings: Annotated[Settings, Depends(get_settings)]) -> SessionSigner:
    return SessionSigner(settings.secret_key)


async def db_session() -> AsyncIterator[AsyncSession]:
    async with session_factory()() as s:
        yield s


async def resolve_session_user(
    session: AsyncSession, signer: SessionSigner, raw_cookie: str | None,
) -> User | None:
    """The single gate for cookie auth: every surface that accepts the session
    cookie (API deps, /api/auth/me, stream/waveform, WS, tusd hook) resolves
    the user here. Returns ``None`` unless the signature is valid, the user id
    is a UUID, the user exists and is not disabled, and the cookie's version
    matches ``User.session_version`` (bumping it revokes every old cookie)."""
    if not raw_cookie:
        return None
    data = signer.read(raw_cookie)
    if data is None:
        return None
    try:
        user_id = uuid.UUID(data.user_id)
    except ValueError:
        return None
    user = await session.get(User, user_id)
    if user is None or user.disabled_at is not None:
        return None
    if data.version != user.session_version:
        return None
    return user


async def current_user(
    session: Annotated[AsyncSession, Depends(db_session)],
    signer: Annotated[SessionSigner, Depends(get_signer)],
    session_cookie: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> User:
    if not session_cookie:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not authenticated")
    user = await resolve_session_user(session, signer, session_cookie)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid session")
    return user


async def require_admin(user: Annotated[User, Depends(current_user)]) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin only")
    return user


async def require_can_monitor(
    user: Annotated[User, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(db_session)],
) -> User:
    """Gate for monitor + discovery endpoints. Admins always pass; other users
    pass only when the global ``monitors_allow_all_users`` setting is on."""
    if user.role == "admin":
        return user
    config = await get_config(session)
    if not config.monitors_allow_all_users:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="monitoring is admin-only"
        )
    return user
