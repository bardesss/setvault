from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from setvault_core.models.catalog import Artist, LiveSet, LiveSetArtist, Party, Series, Venue
from setvault_core.models.enrichment import ProviderConfig
from setvault_core.models.identity import User
from setvault_core.models.tracklist import Track
from setvault_core.schemas.catalog import (
    ArtistIn,
    ArtistOut,
    ArtistPatchIn,
    PartyIn,
    PartyOut,
    PartyPatchIn,
    SeriesIn,
    SeriesOut,
    SeriesPatchIn,
    VenueIn,
    VenueOut,
    VenuePatchIn,
)
from setvault_core.services.artist_enrich import enrich_artist_entity
from setvault_core.services.audit import log as audit_log
from setvault_core.services.catalog import (
    LookupKind,
    list_sets_for_entity,
    slugify,
    unique_slug,
)
from setvault_core.services.catalog import lookup as catalog_lookup
from setvault_core.services.catalog_merge import merge_entities, unmerge_entity
from setvault_core.services.enrichment import select_providers_for_capability
from setvault_providers.base import Capability
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_web.config import get_settings
from setvault_web.deps import current_user, db_session, parse_uuid, require_admin

router = APIRouter(prefix="/api/catalog", tags=["catalog"])


def _artist_out(a: Artist) -> ArtistOut:
    return ArtistOut(
        id=str(a.id),
        name=a.name,
        slug=a.slug,
        country=a.country,
        bio=a.bio,
        aliases=list(a.aliases or []),
        image_url=a.image_url,
    )


def _venue_out(v: Venue) -> VenueOut:
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


def _series_out(s: Series) -> SeriesOut:
    return SeriesOut(
        id=str(s.id),
        slug=s.slug,
        name=s.name,
        description=s.description,
        image_url=s.image_url,
    )


def _party_out(p: Party) -> PartyOut:
    return PartyOut(
        id=str(p.id),
        name=p.name,
        slug=p.slug,
        venue=_venue_out(p.venue) if p.venue is not None else None,
        series=_series_out(p.series) if p.series is not None else None,
        date=p.date,
        description=p.description,
    )


async def _create(session: AsyncSession, row, kind: str, body: BaseModel, user: User) -> None:
    """Insert ``row`` with a ``{kind}.created`` audit row; 409 on a slug clash."""
    session.add(row)
    try:
        await session.flush()
        await audit_log(
            session,
            actor_user_id=user.id,
            action=f"{kind}.created",
            target_type=type(row).__name__,
            target_id=str(row.id),
            after={**body.model_dump(mode="json"), "slug": row.slug},
        )
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=f"{kind} slug already exists") from exc


# -------- Lookup --------


class LookupOut(BaseModel):
    id: str
    name: str
    slug: str
    hint: str | None


# Registered before the "/{kind}/{slug}" routes.
@router.get("/lookup", response_model=list[LookupOut])
async def lookup_entities(
    kind: LookupKind,
    session: Annotated[AsyncSession, Depends(db_session)],
    _: Annotated[object, Depends(current_user)],
    q: Annotated[str, Query(max_length=200)] = "",
    limit: Annotated[int, Query(ge=1)] = 10,
):
    """Typeahead for the set editor: ``limit`` is capped at 25."""
    rows = await catalog_lookup(session, kind, q, limit)
    return [LookupOut(id=r.id, name=r.name, slug=r.slug, hint=r.hint) for r in rows]


# -------- Artists --------


@router.post("/artists", response_model=ArtistOut, status_code=201)
async def create_artist(
    body: ArtistIn,
    session: Annotated[AsyncSession, Depends(db_session)],
    user: Annotated[User, Depends(current_user)],
):
    row = Artist(
        name=body.name,
        slug=await unique_slug(session, Artist, slugify(body.name), name=body.name),
        country=body.country,
        bio=body.bio,
        aliases=list(body.aliases),
        image_url=body.image_url,
    )
    await _create(session, row, "artist", body, user)
    return _artist_out(row)


@router.get("/artists/{slug}", response_model=ArtistOut)
async def get_artist(
    slug: str,
    session: Annotated[AsyncSession, Depends(db_session)],
    _: Annotated[object, Depends(current_user)],
):
    row = (
        await session.execute(
            select(Artist).where(Artist.slug == slug, Artist.merged_into_id.is_(None))
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="artist not found")
    return _artist_out(row)


# -------- Venues --------


@router.post("/venues", response_model=VenueOut, status_code=201)
async def create_venue(
    body: VenueIn,
    session: Annotated[AsyncSession, Depends(db_session)],
    user: Annotated[User, Depends(current_user)],
):
    row = Venue(
        name=body.name,
        slug=await unique_slug(session, Venue, slugify(body.name), name=body.name),
        kind=body.kind,
        city_or_area=body.city_or_area,
        country=body.country,
        capacity=body.capacity,
        website=body.website,
    )
    await _create(session, row, "venue", body, user)
    return _venue_out(row)


@router.get("/venues/{slug}", response_model=VenueOut)
async def get_venue(
    slug: str,
    session: Annotated[AsyncSession, Depends(db_session)],
    _: Annotated[object, Depends(current_user)],
):
    row = (
        await session.execute(
            select(Venue).where(Venue.slug == slug, Venue.merged_into_id.is_(None))
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="venue not found")
    return _venue_out(row)


# -------- Series --------


@router.post("/series", response_model=SeriesOut, status_code=201)
async def create_series(
    body: SeriesIn,
    session: Annotated[AsyncSession, Depends(db_session)],
    user: Annotated[User, Depends(current_user)],
):
    row = Series(
        name=body.name,
        slug=await unique_slug(session, Series, slugify(body.name), name=body.name),
        description=body.description,
        image_url=body.image_url,
    )
    await _create(session, row, "series", body, user)
    return _series_out(row)


@router.get("/series/{slug}", response_model=SeriesOut)
async def get_series(
    slug: str,
    session: Annotated[AsyncSession, Depends(db_session)],
    _: Annotated[object, Depends(current_user)],
):
    row = (
        await session.execute(
            select(Series).where(Series.slug == slug, Series.merged_into_id.is_(None))
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="series not found")
    return _series_out(row)


# -------- Parties --------


@router.post("/parties", response_model=PartyOut, status_code=201)
async def create_party(
    body: PartyIn,
    session: Annotated[AsyncSession, Depends(db_session)],
    user: Annotated[User, Depends(current_user)],
):
    bad = {"status_code": 422, "detail": "invalid id"}
    venue_uuid = parse_uuid(body.venue_id, **bad) if body.venue_id else None
    series_uuid = parse_uuid(body.series_id, **bad) if body.series_id else None
    if venue_uuid is not None and await session.get(Venue, venue_uuid) is None:
        raise HTTPException(status_code=422, detail="unknown venue_id")
    if series_uuid is not None and await session.get(Series, series_uuid) is None:
        raise HTTPException(status_code=422, detail="unknown series_id")
    row = Party(
        name=body.name,
        slug=await unique_slug(session, Party, slugify(body.name), name=body.name),
        venue_id=venue_uuid,
        series_id=series_uuid,
        date=body.date,
        description=body.description,
    )
    await _create(session, row, "party", body, user)
    await session.refresh(row, attribute_names=["venue", "series"])
    return _party_out(row)


@router.get("/parties/{slug}", response_model=PartyOut)
async def get_party(
    slug: str,
    session: Annotated[AsyncSession, Depends(db_session)],
    _: Annotated[object, Depends(current_user)],
):
    row = (
        await session.execute(
            select(Party).where(Party.slug == slug, Party.merged_into_id.is_(None))
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="party not found")
    return _party_out(row)


# -------- Helpers --------


async def _get_by_slug(session, model, slug):
    row = (await session.execute(
        select(model).where(model.slug == slug, model.merged_into_id.is_(None))
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    return row


# -------- Entity edits --------


@router.patch("/artists/{slug}", response_model=ArtistOut)
async def edit_artist(
    slug: str,
    body: ArtistPatchIn,
    session: Annotated[AsyncSession, Depends(db_session)],
    user: Annotated[User, Depends(current_user)],
):
    row = await _get_by_slug(session, Artist, slug)
    patch = body.model_dump(exclude_unset=True)
    for field, value in patch.items():
        if field == "aliases" and value is None:
            continue  # treat null as "no change" — column is NOT NULL
        setattr(row, field, value)
    await audit_log(
        session,
        actor_user_id=user.id,
        action="artist.edited",
        target_type=Artist.__name__,
        target_id=str(row.id),
        after=patch,
    )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=409, detail="could not save — conflicting or invalid value"
        ) from exc
    return _artist_out(row)


@router.patch("/venues/{slug}", response_model=VenueOut)
async def edit_venue(
    slug: str,
    body: VenuePatchIn,
    session: Annotated[AsyncSession, Depends(db_session)],
    user: Annotated[User, Depends(current_user)],
):
    row = await _get_by_slug(session, Venue, slug)
    patch = body.model_dump(exclude_unset=True)
    for field, value in patch.items():
        setattr(row, field, value)
    await audit_log(
        session,
        actor_user_id=user.id,
        action="venue.edited",
        target_type=Venue.__name__,
        target_id=str(row.id),
        after=patch,
    )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=409, detail="could not save — conflicting or invalid value"
        ) from exc
    return _venue_out(row)


@router.patch("/series/{slug}", response_model=SeriesOut)
async def edit_series(
    slug: str,
    body: SeriesPatchIn,
    session: Annotated[AsyncSession, Depends(db_session)],
    user: Annotated[User, Depends(current_user)],
):
    row = await _get_by_slug(session, Series, slug)
    patch = body.model_dump(exclude_unset=True)
    for field, value in patch.items():
        setattr(row, field, value)
    await audit_log(
        session,
        actor_user_id=user.id,
        action="series.edited",
        target_type=Series.__name__,
        target_id=str(row.id),
        after=patch,
    )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=409, detail="could not save — conflicting or invalid value"
        ) from exc
    return _series_out(row)


@router.patch("/parties/{slug}", response_model=PartyOut)
async def edit_party(
    slug: str,
    body: PartyPatchIn,
    session: Annotated[AsyncSession, Depends(db_session)],
    user: Annotated[User, Depends(current_user)],
):
    row = await _get_by_slug(session, Party, slug)
    patch = body.model_dump(exclude_unset=True)
    try:
        for field in ("venue_id", "series_id"):
            if field in patch and patch[field] is not None:
                patch[field] = uuid.UUID(patch[field])
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail="invalid venue_id or series_id"
        ) from exc
    for field, model in (("venue_id", Venue), ("series_id", Series)):
        ref = patch.get(field)
        if ref is not None and await session.get(model, ref) is None:
            raise HTTPException(status_code=422, detail=f"unknown {field}")
    for field, value in patch.items():
        setattr(row, field, value)
    await audit_log(
        session,
        actor_user_id=user.id,
        action="party.edited",
        target_type=Party.__name__,
        target_id=str(row.id),
        after=body.model_dump(exclude_unset=True, mode="json"),
    )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=409, detail="could not save — conflicting or invalid value"
        ) from exc
    await session.refresh(row, attribute_names=["venue", "series"])
    return _party_out(row)


# -------- Merge / unmerge / delete / enrich --------

_KIND_MODEL = {"artists": Artist, "venues": Venue, "parties": Party, "series": Series}
_KIND_NAME = {"artists": "artist", "venues": "venue", "parties": "party", "series": "series"}

_OUT = {
    "artists": _artist_out,
    "venues": _venue_out,
    "parties": _party_out,
    "series": _series_out,
}

_DELETE_GUARDS: dict[str, list] = {
    "artists": [(LiveSetArtist, LiveSetArtist.artist_id), (Track, Track.primary_artist_id)],
    "venues": [(LiveSet, LiveSet.venue_id), (Party, Party.venue_id)],
    "parties": [(LiveSet, LiveSet.party_id)],
    "series": [(Party, Party.series_id)],
}


class MergeIn(BaseModel):
    survivor_id: str


@router.post("/artists/{slug}/enrich")
async def enrich_artist_endpoint(
    slug: str,
    session: Annotated[AsyncSession, Depends(db_session)],
    _: Annotated[User, Depends(current_user)],
):
    artist = await _get_by_slug(session, Artist, slug)
    configs = (await session.execute(select(ProviderConfig))).scalars().all()
    providers = select_providers_for_capability(
        configs, Capability.ENRICH_ARTIST, secret_key=get_settings().secret_key,
    )
    written = await enrich_artist_entity(session, artist=artist, providers=providers)
    await session.commit()
    return {"written": written}


@router.post("/{kind}/{loser_id}/merge")
async def merge_entity_endpoint(
    kind: str,
    loser_id: uuid.UUID,
    body: MergeIn,
    session: Annotated[AsyncSession, Depends(db_session)],
    admin: Annotated[User, Depends(require_admin)],
    dry_run: bool = False,
):
    name = _KIND_NAME.get(kind)
    model = _KIND_MODEL.get(kind)
    if name is None or model is None:
        raise HTTPException(status_code=404, detail="unknown kind")
    try:
        survivor_id = uuid.UUID(body.survivor_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid survivor_id") from exc
    if dry_run:
        survivor = await session.get(model, survivor_id)
        loser = await session.get(model, loser_id)
        if survivor is None or loser is None:
            raise HTTPException(status_code=404, detail="not found")
        return {"preview": {"survivor": survivor.name, "loser": loser.name}}
    try:
        survivor = await merge_entities(
            session, kind=name, survivor_id=survivor_id, loser_id=loser_id, actor_id=admin.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await session.commit()
    if kind == "parties":
        await session.refresh(survivor, attribute_names=["venue", "series"])
    return _OUT[kind](survivor)


@router.post("/{kind}/{loser_id}/unmerge", status_code=204)
async def unmerge_entity_endpoint(
    kind: str,
    loser_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(db_session)],
    admin: Annotated[User, Depends(require_admin)],
):
    name = _KIND_NAME.get(kind)
    if name is None:
        raise HTTPException(status_code=404, detail="unknown kind")
    try:
        await unmerge_entity(session, kind=name, loser_id=loser_id, actor_id=admin.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await session.commit()


@router.delete("/{kind}/{slug}", status_code=204)
async def delete_entity(
    kind: str,
    slug: str,
    session: Annotated[AsyncSession, Depends(db_session)],
    admin: Annotated[User, Depends(require_admin)],
):
    model = _KIND_MODEL.get(kind)
    if model is None:
        raise HTTPException(status_code=404, detail="unknown kind")
    row = await _get_by_slug(session, model, slug)
    guards = _DELETE_GUARDS.get(kind, [])
    for ref_model, ref_col in guards:
        in_use = (await session.execute(
            select(ref_model).where(ref_col == row.id).limit(1)
        )).first()
        if in_use is not None:
            raise HTTPException(
                status_code=409, detail="entity is referenced — merge it instead"
            )
    await audit_log(
        session,
        actor_user_id=admin.id,
        action=f"{_KIND_NAME[kind]}.deleted",
        target_type=model.__name__,
        target_id=str(row.id),
        before={"name": row.name},
    )
    await session.delete(row)
    await session.commit()


# -------- Sets by entity --------


def _set_summary_dict(ls: LiveSet) -> dict:
    """Return a minimal set summary dict for the sets-by-entity endpoint.

    SetSummaryOut lacks venue; SetDetailOut is too heavy to build here (needs
    stream URLs). We return a plain dict with the fields the frontend needs.
    """
    return {
        "slug": ls.slug,
        "title": ls.title,
        "artists": [
            {"id": str(la.artist.id), "name": la.artist.name, "slug": la.artist.slug}
            for la in ls.artists
        ],
        "venue": {"name": ls.venue.name, "slug": ls.venue.slug} if ls.venue else None,
        "date": ls.date.isoformat() if ls.date else None,
        "duration_seconds": ls.duration_seconds,
    }


@router.get("/{kind}/{slug}/sets")
async def entity_sets(
    kind: str,
    slug: str,
    session: Annotated[AsyncSession, Depends(db_session)],
    _: Annotated[object, Depends(current_user)],
):
    model = _KIND_MODEL.get(kind)
    if model is None:
        raise HTTPException(status_code=404, detail="unknown entity kind")
    row = (await session.execute(
        select(model).where(model.slug == slug, model.merged_into_id.is_(None))
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    sets = await list_sets_for_entity(session, kind=_KIND_NAME[kind], entity_id=row.id)
    return {"items": [_set_summary_dict(s) for s in sets]}
