"""Admin -> Sources -> YouTube cookies: the cookies.txt yt-dlp sends to YouTube.

The file is uploaded as the raw request body (no multipart) and stored by
``setvault_core.services.ytdlp_cookies``. Responses and audit events carry
only whether a file is set, when it was uploaded and how many YouTube cookies
it holds: the cookies are a logged-in session and are never sent back.
"""
from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from setvault_core.models.identity import User
from setvault_core.services import ytdlp_cookies as _cookies
from setvault_core.services.audit import log as audit_log
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_web.deps import current_user, db_session, require_admin

router = APIRouter(prefix="/api/admin/ytdlp-cookies", tags=["admin"])


async def _read_capped(request: Request) -> bytes:
    """The request body, or 400 once it passes the size limit."""
    limit = _cookies.MAX_COOKIES_BYTES
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise HTTPException(
                status_code=400, detail=f"cookies file is larger than {limit // 1024} KB",
            )
        chunks.append(chunk)
    return b"".join(chunks)


@router.get("")
async def get_status(_: Annotated[object, Depends(require_admin)]):
    return await asyncio.to_thread(_cookies.cookies_status)


@router.put("")
async def upload(
    request: Request,
    session: Annotated[AsyncSession, Depends(db_session)],
    admin: Annotated[User, Depends(current_user)],
    _: Annotated[object, Depends(require_admin)],
):
    data = await _read_capped(request)
    try:
        status = await asyncio.to_thread(_cookies.save_cookies, data)
    except _cookies.InvalidCookiesError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await audit_log(
        session, actor_user_id=admin.id, action="ytdlp_cookies.uploaded",
        target_type="ytdlp_cookies", after={"youtube_cookies": status["youtube_cookies"]},
    )
    await session.commit()
    return status


@router.delete("", status_code=204)
async def remove(
    session: Annotated[AsyncSession, Depends(db_session)],
    admin: Annotated[User, Depends(current_user)],
    _: Annotated[object, Depends(require_admin)],
) -> Response:
    if not await asyncio.to_thread(_cookies.remove_cookies):
        raise HTTPException(status_code=404, detail="no YouTube cookies set")
    await audit_log(
        session, actor_user_id=admin.id, action="ytdlp_cookies.removed",
        target_type="ytdlp_cookies",
    )
    await session.commit()
    return Response(status_code=204)
