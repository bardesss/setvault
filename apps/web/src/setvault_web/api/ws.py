from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from redis.asyncio import Redis
from setvault_core.db import session_factory
from setvault_core.progress import channel_for_set
from setvault_core.services.sessions import SESSION_COOKIE, SessionSigner

from setvault_web.config import get_settings
from setvault_web.deps import resolve_session_user

router = APIRouter()


@router.websocket("/ws/sets/{set_id}/progress")
async def progress_ws(ws: WebSocket, set_id: str) -> None:
    settings = get_settings()
    session_cookie = ws.cookies.get(SESSION_COOKIE)
    # Short-lived DB session: only the auth check needs it, not the stream.
    async with session_factory()() as session:
        user = await resolve_session_user(
            session, SessionSigner(settings.secret_key), session_cookie,
        )
    if user is None:
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    await ws.accept()

    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    pubsub = redis.pubsub()
    await pubsub.subscribe(channel_for_set(set_id))
    try:
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=15)
            if message is not None and message.get("type") == "message":
                await ws.send_text(message["data"])
            else:
                await ws.send_text('{"kind":"ping"}')  # keep-alive
    except WebSocketDisconnect:
        pass
    finally:
        await pubsub.unsubscribe(channel_for_set(set_id))
        await pubsub.close()
        await redis.close()
