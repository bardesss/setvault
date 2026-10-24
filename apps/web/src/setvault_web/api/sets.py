from __future__ import annotations

import mimetypes
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Cookie, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from setvault_core.jobs.apply_naming import enqueue_apply_naming
from setvault_core.models.catalog import (
    Artist,
    LiveSet,
    LiveSetArtist,
    LiveSetTag,
    MediaRoot,
    Party,
    Tag,
    Venue,
)
from setvault_core.models.engagement import UserSetState
from setvault_core.models.identity import User
from setvault_core.models.upgrades import SetUpgradeEvent
from setvault_core.schemas.catalog import PartyOut, SeriesOut, VenueOut
from setvault_core.schemas.sets import (
    SetArtistOut,
    SetDetailOut,
    SetFacetsOut,
    SetFacetTagOut,
    SetListOut,
    SetPatchIn,
    SetQualityOut,
    SetSummaryOut,
    SetUpgradeHistoryOut,
    VenueRefOut,
)
from setvault_core.services.audio_quality import quality_label
from setvault_core.services.audit import log as audit_log
from setvault_core.services.favorites import is_favorite
from setvault_core.services.notifications import event_labels, source_name
from setvault_core.services.sessions import SESSION_COOKIE, SessionSigner
from setvault_core.services.set_merge import TRACKLIST_KEPT
from setvault_core.services.sets import UnknownArtistError, replace_artists, replace_tags
from setvault_core.services.signed_urls import verify_stream_sig
from setvault_core.services.system_config import get_config
from sqlalchemy import exists, extract, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_web.config import Settings, get_settings
from setvault_web.deps import (
    current_user,
    db_session,
    parse_uuid,
    require_admin,
    resolve_session_user,
)

router = APIRouter(prefix="/api/sets", tags=["sets"])


async def _stream_authorize(
    live: LiveSet,
    *,
    session: AsyncSession,
    sig: str | None,
    exp: int | None,
    session_cookie: str | None,
    signer: SessionSigner,
    secret_key: str,
) -> None:
    """Authorize access to a set's stream/waveform.

    Order:
      1. If LiveSet.embed_allowed is True, anonymous access is permitted.
      2. If a valid ``?sig=&exp=`` pair is present for this slug, allow. The
         signature is HMAC-SHA256 over ``slug:exp`` with secret_key; this is
         the path podcast apps use, via short-TTL URLs embedded in RSS
         enclosures.
      3. If the session cookie resolves to an active user whose session
         version matches (``deps.resolve_session_user``), allow.
      4. Otherwise, 401.

    The rss-scope ApiToken does *not* authorize stream access by itself - it
    only authorizes feed-XML fetches. Embedding a long-lived token in every
    enclosure URL would leak it via referer/log/CDN; signatures bind a stream
    URL to one slug and a 24h window instead.
    """
    if live.embed_allowed:
        return
    if sig and exp is not None and verify_stream_sig(
        secret_key=secret_key, slug=live.slug, exp=exp, sig=sig,
    ):
        return
    if await resolve_session_user(session, signer, session_cookie) is not None:
        return
    raise HTTPException(status_code=401, detail="not authenticated")


def stream_url(live: LiveSet) -> str:
    """The set's stream URL. ``v`` is the gain baked into the stream file, so a
    re-gained stream is a new URL to the service-worker cache; the stream
    route ignores it."""
    return f"/api/sets/{live.slug}/stream?v={live.stream_gain_db or 0.0:.1f}"


async def _tag_names_for(session: AsyncSession, live_id: uuid.UUID) -> list[str]:
    rows = (
        await session.execute(
            select(Tag.name)
            .join(LiveSetTag, LiveSetTag.tag_id == Tag.id)
            .where(LiveSetTag.live_set_id == live_id)
            .order_by(Tag.name)
        )
    ).scalars().all()
    return list(rows)


def _artists_out(live: LiveSet) -> list[SetArtistOut]:
    return [
        SetArtistOut(
            id=str(a.artist.id),
            name=a.artist.name,
            slug=a.artist.slug,
            role=a.role,
        )
        for a in live.artists
    ]


def _venue_out(v) -> VenueOut:
    return VenueOut(
        id=str(v.id),
        slug=v.slug,
        name=v.name,
        kind=v.kind,
        city_or_area=v.city_or_area,
        country=v.country,
        capacity=v.capacity,
        website=v.website,
    )


def _series_out(s) -> SeriesOut:
    return SeriesOut(
        id=str(s.id),
        slug=s.slug,
        name=s.name,
        description=s.description,
        image_url=s.image_url,
    )


def _party_out(p) -> PartyOut:
    return PartyOut(
        id=str(p.id),
        name=p.name,
        slug=p.slug,
        venue=_venue_out(p.venue) if p.venue is not None else None,
        series=_series_out(p.series) if p.series is not None else None,
        date=p.date,
        description=p.description,
    )


async def tags_by_set(
    session: AsyncSession, set_ids: list[uuid.UUID],
) -> dict[uuid.UUID, list[str]]:
    """Tag names for many sets in one grouped query (no N+1)."""
    out: dict[uuid.UUID, list[str]] = {}
    if not set_ids:
        return out
    tag_rows = (
        await session.execute(
            select(LiveSetTag.live_set_id, Tag.name)
            .join(Tag, Tag.id == LiveSetTag.tag_id)
            .where(LiveSetTag.live_set_id.in_(set_ids))
            .order_by(Tag.name)
        )
    ).all()
    for sid, name in tag_rows:
        out.setdefault(sid, []).append(name)
    return out


def summary_out(r: LiveSet, tags: list[str]) -> SetSummaryOut:
    return SetSummaryOut(
        id=str(r.id),
        slug=r.slug,
        title=r.title,
        date=r.date,
        duration_seconds=r.duration_seconds,
        set_type=r.set_type,
        status=r.status,
        artists=_artists_out(r),
        tags=tags,
        created_at=r.created_at,
        venue=(
            VenueRefOut(name=r.venue.name, slug=r.venue.slug, kind=r.venue.kind)
            if r.venue is not None else None
        ),
    )


def _published():
    return (LiveSet.deleted_at.is_(None), LiveSet.status == "published")


def _like_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@router.get("", response_model=SetListOut)
async def list_sets(
    session: Annotated[AsyncSession, Depends(db_session)],
    _: Annotated[object, Depends(current_user)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    q: Annotated[str | None, Query(max_length=200)] = None,
    tag: Annotated[str | None, Query(max_length=80)] = None,
    year: Annotated[int | None, Query(ge=1, le=9999)] = None,
    venue_kind: Annotated[str | None, Query(max_length=32)] = None,
    sort: Literal["recent", "date", "title", "duration"] = "date",
):
    conds = list(_published())
    if q:
        pattern = f"%{_like_escape(q.strip())}%"
        conds.append(or_(
            LiveSet.title.ilike(pattern, escape="\\"),
            exists().where(
                LiveSetArtist.live_set_id == LiveSet.id,
                LiveSetArtist.artist_id == Artist.id,
                Artist.name.ilike(pattern, escape="\\"),
            ),
        ))
    if tag:
        conds.append(exists().where(
            LiveSetTag.live_set_id == LiveSet.id,
            LiveSetTag.tag_id == Tag.id,
            Tag.slug == tag,
        ))
    if year is not None:
        conds.append(extract("year", LiveSet.date) == year)
    if venue_kind:
        conds.append(exists().where(
            Venue.id == LiveSet.venue_id, Venue.kind == venue_kind,
        ))
    total = (
        await session.execute(select(func.count()).select_from(LiveSet).where(*conds))
    ).scalar_one()
    if sort == "recent":
        order = [LiveSet.created_at.desc(), LiveSet.id]
    elif sort == "title":
        order = [func.lower(LiveSet.title), LiveSet.id]
    elif sort == "duration":
        order = [LiveSet.duration_seconds.desc().nullslast(), LiveSet.id]
    else:
        order = [LiveSet.date.desc().nullslast(), LiveSet.created_at.desc(), LiveSet.id]
    rows = (
        await session.execute(
            select(LiveSet).where(*conds).order_by(*order).limit(limit).offset(offset)
        )
    ).scalars().unique().all()
    tags = await tags_by_set(session, [r.id for r in rows])
    items = [summary_out(r, tags.get(r.id, [])) for r in rows]
    return SetListOut(items=items, total=int(total))


# Registered before "/{slug}" so "facets" is not treated as a slug.
@router.get("/facets", response_model=SetFacetsOut)
async def facets(
    session: Annotated[AsyncSession, Depends(db_session)],
    _: Annotated[object, Depends(current_user)],
):
    pub = _published()
    tag_rows = (
        await session.execute(
            select(Tag.slug, Tag.name, func.count(LiveSet.id))
            .join(LiveSetTag, LiveSetTag.tag_id == Tag.id)
            .join(LiveSet, LiveSet.id == LiveSetTag.live_set_id)
            .where(*pub)
            .group_by(Tag.id)
            .order_by(func.count(LiveSet.id).desc(), Tag.name)
        )
    ).all()
    year_col = extract("year", LiveSet.date)
    years = (
        await session.execute(
            select(year_col).where(*pub, LiveSet.date.is_not(None))
            .distinct().order_by(year_col.desc())
        )
    ).scalars().all()
    kinds = (
        await session.execute(
            select(Venue.kind).join(LiveSet, LiveSet.venue_id == Venue.id)
            .where(*pub).distinct().order_by(Venue.kind)
        )
    ).scalars().all()
    return SetFacetsOut(
        tags=[SetFacetTagOut(slug=s, name=n, count=int(c)) for s, n, c in tag_rows],
        years=[int(y) for y in years],
        venue_kinds=list(kinds),
    )


@router.get("/{slug}", response_model=SetDetailOut)
async def show_set(
    slug: str,
    session: Annotated[AsyncSession, Depends(db_session)],
    user: Annotated[User, Depends(current_user)],
):
    row = (
        await session.execute(
            select(LiveSet).where(
                LiveSet.slug == slug, LiveSet.deleted_at.is_(None)
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    quality = None
    if row.quality_tier:
        quality = SetQualityOut(
            tier=row.quality_tier,
            label=quality_label(
                row.quality_tier, row.audio_codec, row.audio_bitrate_kbps,
                source_name(row.source_type, row.source_url)),
        )
    events = (
        await session.execute(
            select(SetUpgradeEvent)
            .where(
                SetUpgradeEvent.live_set_id == row.id,
                SetUpgradeEvent.outcome.in_(("upgraded", "merged")),
            )
            .order_by(SetUpgradeEvent.created_at.desc(), SetUpgradeEvent.id.desc())
            .limit(5)
        )
    ).scalars().all()
    history = []
    for ev in events:
        from_label, to_label = event_labels(ev)
        history.append(SetUpgradeHistoryOut(
            id=str(ev.id), created_at=ev.created_at,
            from_label=from_label, to_label=to_label, outcome=ev.outcome,
            tracklist_kept=ev.outcome == "merged" and ev.reason == TRACKLIST_KEPT))
    return SetDetailOut(
        id=str(row.id),
        slug=row.slug,
        title=row.title,
        date=row.date,
        duration_seconds=row.duration_seconds,
        set_type=row.set_type,
        status=row.status,
        artists=_artists_out(row),
        tags=await _tag_names_for(session, row.id),
        created_at=row.created_at,
        party=_party_out(row.party) if row.party else None,
        venue=_venue_out(row.venue) if row.venue else None,
        description=row.description,
        audio_stream_url=stream_url(row),
        waveform_url=f"/api/sets/{slug}/waveform" if row.waveform_path else None,
        normalized_lufs=row.normalized_lufs,
        embed_allowed=row.embed_allowed,
        quality=quality,
        upgrades_enabled=row.upgrades_enabled,
        auto_upgrades_enabled=bool((await get_config(session)).auto_upgrades_enabled),
        upgrade_history=history,
        is_favorite=await is_favorite(session, user.id, row.id),
    )


@router.patch("/{slug}", response_model=SetDetailOut)
async def edit_set(
    slug: str,
    body: SetPatchIn,
    session: Annotated[AsyncSession, Depends(db_session)],
    user: Annotated[User, Depends(current_user)],
):
    live = (
        await session.execute(
            select(LiveSet).where(
                LiveSet.slug == slug, LiveSet.deleted_at.is_(None)
            )
        )
    ).scalar_one_or_none()
    if live is None:
        raise HTTPException(status_code=404, detail="not found")
    patch = body.model_dump(exclude_unset=True)
    before = await _edit_snapshot(session, live)

    if "title" in patch:
        live.title = body.title
    if "date" in patch:
        live.date = body.date
    if body.set_type is not None:
        live.set_type = body.set_type
    if "party_id" in patch:
        live.party_id = await _ref_id(session, Party, body.party_id, "party_id")
    if "venue_id" in patch:
        live.venue_id = await _ref_id(session, Venue, body.venue_id, "venue_id")
    if "description" in patch:
        live.description = body.description
    if body.upgrades_enabled is not None:
        live.upgrades_enabled = body.upgrades_enabled
    try:
        if body.artists is not None:
            roles: dict[str, str] = {}
            for a in body.artists:
                roles.setdefault(a.id, a.role)
            await replace_artists(session, live, [a.id for a in body.artists], roles)
        elif body.artist_ids is not None:
            await replace_artists(session, live, body.artist_ids)
    except UnknownArtistError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if body.tag_names is not None:
        await replace_tags(session, live, body.tag_names)

    await session.flush()
    after = await _edit_snapshot(session, live)
    changed = [k for k in before if before[k] != after[k]]
    if changed:
        await audit_log(
            session, actor_user_id=user.id, action="set.edited",
            target_type="LiveSet", target_id=str(live.id),
            before={k: before[k] for k in changed},
            after={k: after[k] for k in changed},
        )
    root = await session.get(MediaRoot, live.media_root_id)
    template = root.naming_template if root is not None else None
    await session.commit()
    # Relationships (party, venue) still hold the pre-edit objects.
    await session.refresh(live)
    if (
        template and live.status == "published"
        and any(tok in template for k in changed for tok in _NAMING_TOKENS.get(k, ()))
    ):
        enqueue_apply_naming(live.id)
    return await show_set(slug, session, user)


# Edit fields whose value a naming-template token renders. The title only
# feeds {Slug} through the slug, which an edit never changes.
_NAMING_TOKENS: dict[str, tuple[str, ...]] = {
    "artists": ("{Artist}",),
    "party_id": ("{Party}", "{Series}"),
    "venue_id": ("{Venue}",),
    "date": ("{Date}", "{Year}"),
    "set_type": ("{Type}",),
}


async def _ref_id(session: AsyncSession, model, raw: str | None, field: str) -> uuid.UUID | None:
    """``raw`` as the id of an existing ``model`` row; None stays None (clears)."""
    if raw is None:
        return None
    ref = parse_uuid(raw, status_code=422, detail=f"invalid {field}")
    if await session.get(model, ref) is None:
        raise HTTPException(status_code=422, detail=f"unknown {field}")
    return ref


async def _edit_snapshot(session: AsyncSession, live: LiveSet) -> dict[str, object]:
    """The editable fields of ``live`` in API shape, for the set.edited audit."""
    return {
        "title": live.title,
        "date": live.date.isoformat() if live.date else None,
        "set_type": live.set_type,
        "party_id": str(live.party_id) if live.party_id else None,
        "venue_id": str(live.venue_id) if live.venue_id else None,
        "description": live.description,
        "upgrades_enabled": live.upgrades_enabled,
        "artists": [{"id": str(a.artist_id), "role": a.role} for a in live.artists],
        "tags": await _tag_names_for(session, live.id),
    }


class EmbedToggleIn(BaseModel):
    allowed: bool


class EmbedToggleOut(BaseModel):
    slug: str
    embed_allowed: bool


@router.patch("/{slug}/embed", response_model=EmbedToggleOut)
async def toggle_embed(
    slug: str,
    body: EmbedToggleIn,
    session: Annotated[AsyncSession, Depends(db_session)],
    admin: Annotated[User, Depends(require_admin)],
):
    """Admin-only embed toggle. Writes a set.embed_toggled audit event."""
    from setvault_core.services.audit import log as audit_log

    live = (
        await session.execute(
            select(LiveSet).where(
                LiveSet.slug == slug, LiveSet.deleted_at.is_(None)
            )
        )
    ).scalar_one_or_none()
    if live is None:
        raise HTTPException(status_code=404, detail="not found")
    before = {"embed_allowed": live.embed_allowed}
    live.embed_allowed = body.allowed
    await audit_log(
        session, actor_user_id=admin.id, actor_kind="user",
        action="set.embed_toggled",
        target_type="live_set", target_id=str(live.id),
        before=before, after={"embed_allowed": live.embed_allowed},
    )
    await session.commit()
    return EmbedToggleOut(slug=slug, embed_allowed=live.embed_allowed)


@router.delete("/{slug}", status_code=204)
async def delete_set(
    slug: str,
    session: Annotated[AsyncSession, Depends(db_session)],
    _: Annotated[object, Depends(require_admin)],
):
    live = (
        await session.execute(
            select(LiveSet).where(
                LiveSet.slug == slug, LiveSet.deleted_at.is_(None)
            )
        )
    ).scalar_one_or_none()
    if live is None:
        raise HTTPException(status_code=404, detail="not found")
    now = datetime.now(UTC)
    live.deleted_at = now
    live.purge_after_at = now + timedelta(days=14)
    await session.commit()


@router.get("/{slug}/stream")
async def stream_set(
    slug: str,
    session: Annotated[AsyncSession, Depends(db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    sig: str | None = None,
    exp: int | None = None,
    session_cookie: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
):
    row = (
        await session.execute(
            select(LiveSet).where(
                LiveSet.slug == slug, LiveSet.deleted_at.is_(None)
            )
        )
    ).scalar_one_or_none()
    if row is None or row.streaming_path is None:
        raise HTTPException(status_code=404, detail="not ready")
    await _stream_authorize(
        row, session=session, sig=sig, exp=exp,
        session_cookie=session_cookie,
        signer=SessionSigner(settings.secret_key),
        secret_key=settings.secret_key,
    )
    root = await session.get(MediaRoot, row.media_root_id)
    path = Path(root.host_path) / row.streaming_path
    # Detect media type from extension so test fixtures (e.g. silent.wav) work too;
    # production sets streaming_path to an .opus file so audio/ogg remains the norm.
    guessed, _ = mimetypes.guess_type(str(path))
    return FileResponse(path, media_type=guessed or "audio/ogg")


@router.get("/{slug}/waveform")
async def waveform(
    slug: str,
    session: Annotated[AsyncSession, Depends(db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    sig: str | None = None,
    exp: int | None = None,
    session_cookie: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
):
    row = (
        await session.execute(
            select(LiveSet).where(
                LiveSet.slug == slug, LiveSet.deleted_at.is_(None)
            )
        )
    ).scalar_one_or_none()
    if row is None or row.waveform_path is None:
        raise HTTPException(status_code=404, detail="not ready")
    await _stream_authorize(
        row, session=session, sig=sig, exp=exp,
        session_cookie=session_cookie,
        signer=SessionSigner(settings.secret_key),
        secret_key=settings.secret_key,
    )
    root = await session.get(MediaRoot, row.media_root_id)
    return FileResponse(
        Path(root.host_path) / row.waveform_path,
        media_type="application/json",
    )


class StateOut(BaseModel):
    position_seconds: float
    completed: bool
    playback_rate: float = 1.0


class StateIn(BaseModel):
    position_seconds: float
    completed: bool
    playback_rate: float | None = None


@router.get("/{slug}/state", response_model=StateOut)
async def get_state(
    slug: str,
    user: Annotated[User, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    live = (
        await session.execute(
            select(LiveSet).where(LiveSet.slug == slug, LiveSet.deleted_at.is_(None))
        )
    ).scalar_one_or_none()
    if live is None:
        raise HTTPException(status_code=404, detail="not found")
    state = await session.get(UserSetState, (user.id, live.id))
    return StateOut(
        position_seconds=state.position_seconds if state else 0.0,
        completed=state.completed if state else False,
        playback_rate=state.playback_rate if state else 1.0,
    )


@router.put("/{slug}/state", status_code=204)
async def put_state(
    slug: str,
    body: StateIn,
    user: Annotated[User, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(db_session)],
):
    live = (
        await session.execute(
            select(LiveSet).where(LiveSet.slug == slug, LiveSet.deleted_at.is_(None))
        )
    ).scalar_one_or_none()
    if live is None:
        raise HTTPException(status_code=404, detail="not found")
    state = await session.get(UserSetState, (user.id, live.id))
    if state is None:
        session.add(
            UserSetState(
                user_id=user.id,
                live_set_id=live.id,
                position_seconds=body.position_seconds,
                completed=body.completed,
                playback_rate=body.playback_rate if body.playback_rate is not None else 1.0,
            )
        )
    else:
        state.position_seconds = body.position_seconds
        state.completed = body.completed
        if body.playback_rate is not None:
            state.playback_rate = body.playback_rate
    await session.commit()
