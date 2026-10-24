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


def slugify(text: str) -> str:
    return _ascii_slug(text) or _FALLBACK_SLUG


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


async def lookup(
    session: AsyncSession, kind: LookupKind, q: str, limit: int = 10,
) -> list[LookupRow]:
    """Typeahead search over one catalog kind: case-insensitive substring
    match on the name (and, for artists, the aliases). Merged-away entities
    are left out. Prefix matches come first, then the rest, each by name.
    ``limit`` is capped at ``LOOKUP_MAX``."""
    model = {"artist": Artist, "party": Party, "venue": Venue, "series": Series, "tag": Tag}[kind]
    limit = max(1, min(limit, LOOKUP_MAX))
    term = _like_escape(q.strip().replace(_ALIAS_SEP, ""))
    contains = model.name.ilike(f"%{term}%", escape="\\")
    prefix = model.name.ilike(f"{term}%", escape="\\")
    if model is Artist:
        aliases = func.concat(_ALIAS_SEP, func.array_to_string(Artist.aliases, _ALIAS_SEP))
        contains = or_(contains, aliases.ilike(f"%{term}%", escape="\\"))
        prefix = or_(prefix, aliases.ilike(f"%{_ALIAS_SEP}{term}%", escape="\\"))
    stmt = select(model).where(contains)
    if model is not Tag:
        stmt = stmt.where(model.merged_into_id.is_(None))
    stmt = stmt.order_by(
        case((prefix, 0), else_=1), func.lower(model.name), model.id,
    ).limit(limit)
    rows = (await session.execute(stmt)).scalars().unique().all()

    def hint(row) -> str | None:
        if model is Venue:
            return row.city_or_area
        if model is Party:
            return _party_hint(row)
        return None

    return [LookupRow(id=str(r.id), name=r.name, slug=r.slug, hint=hint(r)) for r in rows]


async def list_sets_for_entity(
    session: AsyncSession, *, kind: EntityKind, entity_id: uuid.UUID,
) -> list[LiveSet]:
    """Published, non-deleted LiveSets referencing the entity, newest first."""
    q = select(LiveSet).where(
        LiveSet.deleted_at.is_(None), LiveSet.status == "published",
    )
    if kind == "artist":
        q = q.join(LiveSetArtist, LiveSetArtist.live_set_id == LiveSet.id).where(
            LiveSetArtist.artist_id == entity_id,
        )
    elif kind == "venue":
        q = q.where(LiveSet.venue_id == entity_id)
    elif kind == "party":
        q = q.where(LiveSet.party_id == entity_id)
    elif kind == "series":
        q = q.join(Party, Party.id == LiveSet.party_id).where(Party.series_id == entity_id)
    q = q.order_by(LiveSet.date.desc().nullslast(), LiveSet.created_at.desc())
    return list((await session.execute(q)).scalars().unique().all())
