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
from setvault_core.models.monitors import Monitor, MonitorDiscovery
from setvault_core.models.system import Job, NotificationConnector
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


class HomeActivityItem(BaseModel):
    id: str
    kind: Literal["set_published", "discovery", "job_failed"]
    at: datetime
    title: str
    href: str
    # job_failed only: the raw job kind, so the client can label it.
    job_kind: str | None = None


HOME_ACTIVITY_LIMIT = 10
HOME_FAILED_JOBS_DAYS = 7


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


@router.get("/home-activity", response_model=list[HomeActivityItem])
async def home_activity(
    user: Annotated[User, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    """Newest-first mix of published sets, discoveries awaiting review and (for
    admins) recently failed jobs. Each source is capped in SQL before merging;
    rows whose subject is gone drop out through the inner joins."""
    items: list[HomeActivityItem] = []

    published = await session.execute(
        select(ActivityEvent.created_at, LiveSet.title, LiveSet.slug, ActivityEvent.id)
        .join(LiveSet, LiveSet.id == ActivityEvent.subject_id)
        .where(
            ActivityEvent.kind == "set.published",
            LiveSet.deleted_at.is_(None),
        )
        .order_by(ActivityEvent.created_at.desc())
        .limit(HOME_ACTIVITY_LIMIT)
    )
    items += [
        HomeActivityItem(
            id=f"set_published:{eid}", kind="set_published", at=at, title=title,
            href=f"/sets/{slug}",
        )
        for at, title, slug, eid in published.all()
    ]

    disc_q = (
        select(MonitorDiscovery.created_at, MonitorDiscovery.title, MonitorDiscovery.id)
        .join(Monitor, Monitor.id == MonitorDiscovery.monitor_id)
        .where(MonitorDiscovery.status == "pending_review")
        .order_by(MonitorDiscovery.created_at.desc())
        .limit(HOME_ACTIVITY_LIMIT)
    )
    if user.role != "admin":
        disc_q = disc_q.where(Monitor.owner_user_id == user.id)
    items += [
        HomeActivityItem(
            id=f"discovery:{did}", kind="discovery", at=at, title=title, href="/discoveries",
        )
        for at, title, did in (await session.execute(disc_q)).all()
    ]

    if user.role == "admin":
        since = datetime.now(UTC) - timedelta(days=HOME_FAILED_JOBS_DAYS)
        failed = await session.execute(
            select(Job.finished_at, Job.kind, Job.id)
            .where(Job.status == "failed", Job.finished_at >= since)
            .order_by(Job.finished_at.desc())
            .limit(HOME_ACTIVITY_LIMIT)
        )
        items += [
            HomeActivityItem(
                id=f"job_failed:{jid}", kind="job_failed", at=at, title=kind, href="/admin/jobs",
                job_kind=kind,
            )
            for at, kind, jid in failed.all()
        ]

    # Newest first; kind then id break ties so equal timestamps order stably.
    items.sort(key=lambda i: (i.at, i.kind, i.id), reverse=True)
    return items[:HOME_ACTIVITY_LIMIT]


@router.get("/home-summary", response_model=HomeSummaryOut)
async def home_summary(
    _: Annotated[User, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    from setvault_core.models.tracklist import TracklistEntry

    window_days = 7
    since = datetime.now(UTC) - timedelta(days=window_days)

    # Published only, like Library. Drafts (held duplicates, unfinished rips)
    # still count towards audio_bytes below: their files use disk.
    sets_total_q = select(func.count(LiveSet.id)).where(
        LiveSet.deleted_at.is_(None), LiveSet.status == "published",
    )
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

    # Original plus stream, over the sets in the vault. Sets not measured yet
    # (NULL, before the size backfill reaches them) count as 0.
    audio_bytes_q = select(
        func.coalesce(func.sum(LiveSet.audio_bytes), 0)
        + func.coalesce(func.sum(LiveSet.stream_bytes), 0)
    ).where(LiveSet.deleted_at.is_(None))

    sets_count = (await session.execute(sets_total_q)).scalar_one() or 0
    audio_bytes = int((await session.execute(audio_bytes_q)).scalar_one() or 0)
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
        audio_bytes=audio_bytes,
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
