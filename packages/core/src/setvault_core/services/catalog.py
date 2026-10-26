from __future__ import annotations

import hashlib
import re
import unicodedata
import uuid
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_core.models.catalog import (
    Artist,
    LiveSet,
    LiveSetArtist,
    Party,
    Series,
    Tag,
    Venue,
)

_SLUG_NON_ALNUM = re.compile(r"[^a-z0-9]+")


_FALLBACK_SLUG = "item"


def _ascii_slug(text: str) -> str:
    norm = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return _SLUG_NON_ALNUM.sub("-", norm.lower()).strip("-")


def slugify(text: str, *, fallback: str = _FALLBACK_SLUG, max_len: int | None = None) -> str:
    slug = _ascii_slug(text)
    if max_len is not None:
        slug = slug[:max_len].rstrip("-")
    return slug or fallback


async def unique_slug(
    session: AsyncSession, model: type, base: str, *, name: str | None = None,
) -> str:
    """A slug for a new ``model`` row that no existing row holds.

    ``base`` is normally ``slugify(name)``. Taken slugs get ``-2``, ``-3``, …
    appended. Merged-away tombstones keep their slug, so they count as taken.
    When ``base`` is the ``item`` fallback (the name had no ASCII letters or
    digits, e.g. 'Кино') and ``name`` is passed, a 6-char hash of the name is
    appended first, so distinct non-Latin names don't all queue up behind
    ``item``. The unique index is still the final arbiter under concurrency.
    """
    if base == _FALLBACK_SLUG and name is not None and not _ascii_slug(name):
        base = f"{_FALLBACK_SLUG}-{hashlib.sha256(name.encode('utf-8')).hexdigest()[:6]}"
    max_len = getattr(model.__table__.c.slug.type, "length", None)
    if max_len:
        base = base[: max_len - 6].rstrip("-") or _FALLBACK_SLUG  # room for "-NNNNN"
    # base is [a-z0-9-] only, so it needs no LIKE escaping.
    taken = set((await session.execute(
        select(model.slug).where(or_(model.slug == base, model.slug.like(f"{base}-%")))
    )).scalars().all())
    candidate, n = base, 2
    while candidate in taken:
        candidate = f"{base}-{n}"
        n += 1
    return candidate


EntityKind = Literal["artist", "venue", "party", "series"]
LookupKind = Literal["artist", "party", "venue", "series", "tag"]

LOOKUP_MAX = 25
# Joins an artist's aliases into one string; a control character no name or
# query contains, so a match can't span two aliases.
_ALIAS_SEP = "\x1f"


@dataclass(frozen=True)
class LookupRow:
    id: str
    name: str
    slug: str
    hint: str | None


def _like_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _party_hint(p: Party) -> str | None:
    parts = [p.date.isoformat() if p.date else None, p.venue.name if p.venue else None]
    return " · ".join(x for x in parts if x) or None


_LOOKUP_MODELS = {"artist": Artist, "party": Party, "venue": Venue, "series": Series, "tag": Tag}


def _match_filter(model, q: str | None) -> tuple[list, object | None]:
    """The shared WHERE for lookup and browse: a case-insensitive substring
    match on the name (and, for artists, the aliases) when ``q`` is given, and
    merged-away entities left out. Also returns the prefix-match expression
    lookup orders by (``None`` without a ``q``)."""
    conds: list = []
    if model is not Tag:
        conds.append(model.merged_into_id.is_(None))
    if q is None or not q.strip():
        return conds, None
    term = _like_escape(q.strip().replace(_ALIAS_SEP, ""))
    contains = model.name.ilike(f"%{term}%", escape="\\")
    prefix = model.name.ilike(f"{term}%", escape="\\")
    if model is Artist:
        aliases = func.concat(_ALIAS_SEP, func.array_to_string(Artist.aliases, _ALIAS_SEP))
        contains = or_(contains, aliases.ilike(f"%{term}%", escape="\\"))
        prefix = or_(prefix, aliases.ilike(f"%{_ALIAS_SEP}{term}%", escape="\\"))
    conds.append(contains)
    return conds, prefix


def _hint(row) -> str | None:
    if isinstance(row, Venue):
        return row.city_or_area
    if isinstance(row, Party):
        return _party_hint(row)
    return None


async def lookup(
    session: AsyncSession, kind: LookupKind, q: str, limit: int = 10,
) -> list[LookupRow]:
    """Typeahead search over one catalog kind: case-insensitive substring
    match on the name (and, for artists, the aliases). Merged-away entities
    are left out. Prefix matches come first, then the rest, each by name.
    ``limit`` is capped at ``LOOKUP_MAX``."""
    model = _LOOKUP_MODELS[kind]
    limit = max(1, min(limit, LOOKUP_MAX))
    conds, prefix = _match_filter(model, q)
    order = [func.lower(model.name), model.id]
    if prefix is not None:
        order.insert(0, case((prefix, 0), else_=1))
    stmt = select(model).where(*conds).order_by(*order).limit(limit)
    rows = (await session.execute(stmt)).scalars().unique().all()
    return [LookupRow(id=str(r.id), name=r.name, slug=r.slug, hint=_hint(r)) for r in rows]


BrowseKind = Literal["artist", "party", "venue", "series"]
BrowseSort = Literal["name", "sets", "recent"]


@dataclass(frozen=True)
class EntityRow(LookupRow):
    set_count: int


def _set_counts(kind: BrowseKind):
    """Published, non-deleted set count per entity id, as a grouped subquery."""
    live = (LiveSet.deleted_at.is_(None), LiveSet.status == "published")
    if kind == "artist":
        key = LiveSetArtist.artist_id
        stmt = select(key.label("entity_id"), func.count(func.distinct(LiveSet.id)).label("n"))
        stmt = stmt.join(LiveSet, LiveSet.id == LiveSetArtist.live_set_id)
    elif kind == "series":
        key = Party.series_id
        stmt = select(key.label("entity_id"), func.count(LiveSet.id).label("n"))
        stmt = stmt.select_from(LiveSet).join(Party, Party.id == LiveSet.party_id)
    else:
        key = LiveSet.venue_id if kind == "venue" else LiveSet.party_id
        stmt = select(key.label("entity_id"), func.count(LiveSet.id).label("n"))
    return stmt.where(*live, key.is_not(None)).group_by(key).subquery()


async def list_entities(
    session: AsyncSession,
    kind: BrowseKind,
    *,
    q: str | None,
    sort: BrowseSort,
    limit: int,
    offset: int,
) -> tuple[list[EntityRow], int]:
    """One page of a catalog kind for the browse pages, with each entity's
    published set count, plus the total matching ``q``. Same match and
    merged-away rules as ``lookup``."""
    model = _LOOKUP_MODELS[kind]
    conds, _ = _match_filter(model, q)
    total = (await session.execute(
        select(func.count()).select_from(model).where(*conds)
    )).scalar_one()
    counts = _set_counts(kind)
    set_count = func.coalesce(counts.c.n, 0)
    if sort == "sets":
        order = [set_count.desc(), func.lower(model.name), model.id]
    elif sort == "recent":
        order = [model.created_at.desc(), model.id]
    else:
        order = [func.lower(model.name), model.id]
    stmt = (
        select(model, set_count)
        .outerjoin(counts, counts.c.entity_id == model.id)
        .where(*conds)
        .order_by(*order)
        .limit(limit)
        .offset(offset)
    )
    rows = (await session.execute(stmt)).all()
    items = [
        EntityRow(id=str(r.id), name=r.name, slug=r.slug, hint=_hint(r), set_count=int(n))
        for r, n in rows
    ]
    return items, int(total)


async def list_sets_for_entity(
    session: AsyncSession,
    *,
    kind: EntityKind,
    entity_id: uuid.UUID,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[LiveSet], int]:
    """One page of the published, non-deleted LiveSets referencing the entity,
    newest first, plus their total."""
    conds = [LiveSet.deleted_at.is_(None), LiveSet.status == "published"]
    if kind == "artist":
        conds.append(LiveSet.id.in_(
            select(LiveSetArtist.live_set_id).where(LiveSetArtist.artist_id == entity_id)
        ))
    elif kind == "venue":
        conds.append(LiveSet.venue_id == entity_id)
    elif kind == "party":
        conds.append(LiveSet.party_id == entity_id)
    elif kind == "series":
        conds.append(LiveSet.party_id.in_(
            select(Party.id).where(Party.series_id == entity_id)
        ))
    total = (await session.execute(
        select(func.count()).select_from(LiveSet).where(*conds)
    )).scalar_one()
    q = (
        select(LiveSet).where(*conds)
        .order_by(LiveSet.date.desc().nullslast(), LiveSet.created_at.desc(), LiveSet.id)
        .limit(limit).offset(offset)
    )
    return list((await session.execute(q)).scalars().unique().all()), int(total)
