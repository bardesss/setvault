from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from setvault_core.models.catalog import Artist, LiveSet, Party, Series, Venue
from setvault_core.services.search import to_tsquery
from sqlalchemy import func, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_web.deps import current_user, db_session

router = APIRouter(prefix="/api/search", tags=["search"])


class SearchSetOut(BaseModel):
    slug: str
    title: str


class SearchArtistOut(BaseModel):
    slug: str
    name: str


class SearchOut(BaseModel):
    sets: list[SearchSetOut]
    artists: list[SearchArtistOut]
    parties: list[dict]
    venues: list[dict]
    series: list[dict]


@router.get("", response_model=SearchOut)
async def search(
    q: str,
    session: Annotated[AsyncSession, Depends(db_session)],
    _: Annotated[object, Depends(current_user)],
) -> SearchOut:
    query = to_tsquery(q)
    if not query:
        return SearchOut(sets=[], artists=[], parties=[], venues=[], series=[])
    tsq = func.to_tsquery("simple", query)

    # Use fully-qualified column refs because LiveSet's joined relationships
    # pull in venues/parties/series, which also have a `search_tsv` column —
    # an unqualified reference triggers a Postgres AmbiguousColumnError.
    sets_tsv = literal_column("live_sets.search_tsv")
    artists_tsv = literal_column("artists.search_tsv")
    parties_tsv = literal_column("parties.search_tsv")
    venues_tsv = literal_column("venues.search_tsv")
    series_tsv = literal_column("series.search_tsv")

    sets = (
        await session.execute(
            select(LiveSet)
            .where(
                LiveSet.deleted_at.is_(None),
                sets_tsv.op("@@")(tsq),
            )
            .order_by(func.ts_rank(sets_tsv, tsq).desc())
            .limit(20)
        )
    ).scalars().all()

    artists = (
        await session.execute(
            select(Artist)
            .where(artists_tsv.op("@@")(tsq), Artist.merged_into_id.is_(None))
            .order_by(func.ts_rank(artists_tsv, tsq).desc())
            .limit(20)
        )
    ).scalars().all()

    parties = (
        await session.execute(
            select(Party)
            .where(parties_tsv.op("@@")(tsq), Party.merged_into_id.is_(None))
            .limit(20)
        )
    ).scalars().all()

    venues = (
        await session.execute(
            select(Venue)
            .where(venues_tsv.op("@@")(tsq), Venue.merged_into_id.is_(None))
            .limit(20)
        )
    ).scalars().all()

    series = (
        await session.execute(
            select(Series)
            .where(series_tsv.op("@@")(tsq), Series.merged_into_id.is_(None))
            .limit(20)
        )
    ).scalars().all()

    return SearchOut(
        sets=[SearchSetOut(slug=s.slug, title=s.title) for s in sets],
        artists=[SearchArtistOut(slug=a.slug, name=a.name) for a in artists],
        parties=[{"slug": p.slug, "name": p.name} for p in parties],
        venues=[{"slug": v.slug, "name": v.name, "kind": v.kind} for v in venues],
        series=[{"slug": s.slug, "name": s.name} for s in series],
    )
