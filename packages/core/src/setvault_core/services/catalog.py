from __future__ import annotations

import hashlib
import re
import unicodedata
import uuid
from typing import Literal

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_core.models.catalog import LiveSet, LiveSetArtist, Party

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
