from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from setvault_core.models.api_token import ApiToken
from setvault_core.models.catalog import LiveSet
from setvault_core.models.engagement import ActivityEvent, UserSetState
from setvault_core.models.identity import NotificationPreference, User
from setvault_core.models.system import NotificationConnector
from setvault_core.schemas.feeds import (
    RssTokenCreateIn,
    RssTokenOut,
    RssTokensListOut,
    RssTokenWithPlaintextOut,
)
from setvault_core.services.api_tokens import mint_api_token, revoke_api_token
from setvault_core.services.password_policy import MIN_PASSWORD_LENGTH
from setvault_core.services.passwords import hash_password, verify_password
from setvault_core.services.sessions import SessionSigner
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_web.api.auth import _issue_session
from setvault_web.config import Settings, get_settings
from setvault_web.deps import current_user, db_session, get_signer, parse_uuid

router = APIRouter(prefix="/api/me", tags=["me"])


class ContinueItem(BaseModel):
    slug: str
    title: str
    position_seconds: float
    duration_seconds: int | None


class ActivityItem(BaseModel):
    kind: str
    subject_type: str
    subject_id: str | None
    payload: dict
    created_at: str


class HomeSummaryOut(BaseModel):
    sets_count: int
    tracks_resolved_count: int
    tracks_needing_ids_count: int
    audio_bytes: int
    deltas_window_days: int
    sets_delta: int
    tracks_resolved_delta: int
    tracks_needing_ids_delta: int


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=MIN_PASSWORD_LENGTH)


@router.post("/change-password", status_code=204)
async def change_password(
    body: ChangePasswordIn,
    response: Response,
    user: Annotated[User, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(db_session)],
    signer: Annotated[SessionSigner, Depends(get_signer)],
):
    if not user.password_hash or not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="current password incorrect")
    user.password_hash = hash_password(body.new_password)
    user.session_version += 1
    await session.commit()
    _issue_session(response, signer, user)


@router.get("/continue-listening", response_model=list[ContinueItem])
async def continue_listening(
    user: Annotated[User, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    stmt = (
        select(UserSetState, LiveSet)
        .join(LiveSet, LiveSet.id == UserSetState.live_set_id)
        .where(
            UserSetState.user_id == user.id,
            UserSetState.completed.is_(False),
            # A few seconds in is "opened", not "listened": skip it.
            UserSetState.position_seconds > 5,
            LiveSet.status == "published",
            LiveSet.deleted_at.is_(None),
            # Within the last 3 % counts as finished when the length is known.
            or_(
                LiveSet.duration_seconds.is_(None),
                LiveSet.duration_seconds <= 0,
                UserSetState.position_seconds < LiveSet.duration_seconds * 0.97,
            ),
        )
        .order_by(UserSetState.updated_at.desc())
        .limit(8)
    )
    rows = (await session.execute(stmt)).all()
    return [
        ContinueItem(
            slug=live.slug,
            title=live.title,
            position_seconds=state.position_seconds,
            duration_seconds=live.duration_seconds,
        )
        for state, live in rows
    ]


@router.get("/activity", response_model=list[ActivityItem])
async def activity(
    user: Annotated[User, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    rows = (
        await session.execute(
            select(ActivityEvent)
            .where(ActivityEvent.user_id == user.id)
            .order_by(ActivityEvent.created_at.desc())
            .limit(30)
        )
    ).scalars().all()
    return [
        ActivityItem(
            kind=e.kind,
            subject_type=e.subject_type,
            subject_id=str(e.subject_id) if e.subject_id else None,
            payload=e.payload,
            created_at=e.created_at.isoformat(),
        )
        for e in rows
    ]


@router.get("/home-summary", response_model=HomeSummaryOut)
async def home_summary(
    _: Annotated[User, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    from setvault_core.models.tracklist import TracklistEntry

    window_days = 7
    since = datetime.now(UTC) - timedelta(days=window_days)

    sets_total_q = select(func.count(LiveSet.id)).where(LiveSet.deleted_at.is_(None))
    sets_recent_q = sets_total_q.where(LiveSet.created_at >= since)

    # "resolved" = status is "resolved" or "acoustid_confirmed" (anything except "raw")
    tracks_resolved_q = select(func.count(TracklistEntry.id)).where(
        TracklistEntry.status != "raw"
    )
    tracks_unresolved_q = select(func.count(TracklistEntry.id)).where(
        TracklistEntry.status == "raw"
    )
    tracks_resolved_recent_q = tracks_resolved_q.where(TracklistEntry.created_at >= since)
    tracks_unresolved_recent_q = tracks_unresolved_q.where(TracklistEntry.created_at >= since)

    sets_count = (await session.execute(sets_total_q)).scalar_one() or 0
    sets_delta = (await session.execute(sets_recent_q)).scalar_one() or 0
    tracks_resolved = (await session.execute(tracks_resolved_q)).scalar_one() or 0
    tracks_unresolved = (await session.execute(tracks_unresolved_q)).scalar_one() or 0
    tracks_resolved_delta = (await session.execute(tracks_resolved_recent_q)).scalar_one() or 0
    tracks_unresolved_delta = (
        await session.execute(tracks_unresolved_recent_q)
    ).scalar_one() or 0

    return HomeSummaryOut(
        sets_count=sets_count,
        tracks_resolved_count=tracks_resolved,
        tracks_needing_ids_count=tracks_unresolved,
        audio_bytes=0,  # no file-size column exists on LiveSet yet
        deltas_window_days=window_days,
        sets_delta=sets_delta,
        tracks_resolved_delta=tracks_resolved_delta,
        tracks_needing_ids_delta=tracks_unresolved_delta,
    )


class NotificationPreferenceOut(BaseModel):
    kind: str
    channel: Literal["email", "in_app", "both", "off"]
    connector_id: str | None = None


class NotificationPreferencesListOut(BaseModel):
    items: list[NotificationPreferenceOut]


class NotificationPreferenceUpsertIn(BaseModel):
    channel: Literal["email", "in_app", "both", "off"]
    connector_id: str | None = None


_ALLOWED_KINDS = {
    "account_security", "mention", "comment_reply", "set_upgraded", "maintenance",
}


@router.get("/notification-preferences", response_model=NotificationPreferencesListOut)
async def list_my_prefs(
    user: Annotated[User, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    rows = (
        await session.execute(
            select(NotificationPreference).where(NotificationPreference.user_id == user.id)
        )
    ).scalars().all()
    return NotificationPreferencesListOut(
        items=[
            NotificationPreferenceOut(
                kind=p.kind,
                channel=p.channel,
                connector_id=str(p.connector_id) if p.connector_id else None,
            )
            for p in rows
        ]
    )


@router.put("/notification-preferences/{kind}", response_model=NotificationPreferenceOut)
async def upsert_my_pref(
    kind: str,
    body: NotificationPreferenceUpsertIn,
    user: Annotated[User, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    if kind not in _ALLOWED_KINDS:
        raise HTTPException(status_code=400, detail="unknown notification kind")
    existing = (
        await session.execute(
            select(NotificationPreference).where(
                NotificationPreference.user_id == user.id,
                NotificationPreference.kind == kind,
            )
        )
    ).scalar_one_or_none()
    connector_uuid = (
        parse_uuid(body.connector_id, status_code=422, detail="invalid id")
        if body.connector_id else None
    )
    if connector_uuid is not None and await session.get(
        NotificationConnector, connector_uuid
    ) is None:
        raise HTTPException(status_code=422, detail="unknown connector_id")
    if existing is None:
        existing = NotificationPreference(
            user_id=user.id,
            kind=kind,
            channel=body.channel,
            connector_id=connector_uuid,
        )
        session.add(existing)
    else:
        existing.channel = body.channel
        existing.connector_id = connector_uuid
    await session.commit()
    return NotificationPreferenceOut(
        kind=existing.kind,
        channel=existing.channel,
        connector_id=str(existing.connector_id) if existing.connector_id else None,
    )


# --- RSS tokens ---------------------------------------------------------------


def _rss_urls(base_url: str, plaintext: str) -> tuple[str, str, str]:
    """Return (favorites, recent, everything) feed URLs for a plaintext token.

    ``base_url`` is the configured BASE_URL; when empty the URLs stay relative
    and the frontend prefixes its own origin.
    """
    base = base_url.rstrip("/")
    return (
        f"{base}/api/feed/favorites/{plaintext}.xml",
        f"{base}/api/feed/recent/{plaintext}.xml",
        f"{base}/api/feed/everything/{plaintext}.xml",
    )


def _token_out_without_urls(row: ApiToken) -> RssTokenOut:
    """Build an RssTokenOut for an existing row (plaintext is gone). URLs are
    blanked since we never persist the plaintext; the user must save the URLs
    from the create response.
    """
    return RssTokenOut(
        id=str(row.id), name=row.name,
        favorites_url="", recent_url="", everything_url="",
        created_at=row.created_at.isoformat(),
        last_used_at=row.last_used_at.isoformat() if row.last_used_at else None,
    )


@router.get("/rss-tokens", response_model=RssTokensListOut)
async def list_my_rss_tokens(
    response: Response,
    user: Annotated[User, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    # Token metadata is per-user and must never land in a shared offline cache.
    response.headers["Cache-Control"] = "no-store"
    rows = (await session.execute(
        select(ApiToken).where(
            ApiToken.user_id == user.id,
            ApiToken.revoked_at.is_(None),
            ApiToken.scopes.any("rss"),
        ).order_by(ApiToken.created_at.desc())
    )).scalars().all()
    return RssTokensListOut(items=[_token_out_without_urls(r) for r in rows])


@router.post("/rss-tokens", response_model=RssTokenWithPlaintextOut, status_code=201)
async def create_my_rss_token(
    body: RssTokenCreateIn,
    user: Annotated[User, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    row, plaintext = await mint_api_token(
        session, user_id=user.id, name=body.name, scopes=["rss"],
    )
    await session.commit()
    fav, recent, everything = _rss_urls(settings.base_url, plaintext)
    return RssTokenWithPlaintextOut(
        id=str(row.id), name=row.name,
        favorites_url=fav, recent_url=recent, everything_url=everything,
        created_at=row.created_at.isoformat(),
        last_used_at=None,
        token=plaintext,
    )


@router.delete("/rss-tokens/{token_id}", status_code=204)
async def revoke_my_rss_token(
    token_id: str,
    user: Annotated[User, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    try:
        tid = uuid.UUID(token_id)
    except ValueError as exc:
        raise HTTPException(status_code=404) from exc
    ok = await revoke_api_token(session, user_id=user.id, token_id=tid)
    if not ok:
        raise HTTPException(status_code=404)
    await session.commit()
