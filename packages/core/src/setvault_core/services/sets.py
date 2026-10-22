from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_core.models.catalog import Artist, LiveSet, LiveSetArtist, LiveSetTag, Tag
from setvault_core.services.catalog import slugify, unique_slug


class UnknownArtistError(ValueError):
    """An artist id that is malformed, missing, or merged away."""


async def replace_artists(
    session: AsyncSession, live: LiveSet, artist_ids: list[str]
) -> None:
    ids: list[uuid.UUID] = []
    for raw in artist_ids:
        try:
            aid = uuid.UUID(raw)
        except (ValueError, AttributeError, TypeError) as exc:
            raise UnknownArtistError(f"invalid artist id: {raw!r}") from exc
        if aid not in ids:
            ids.append(aid)
    if ids:
        valid = set((await session.execute(
            select(Artist.id).where(Artist.id.in_(ids), Artist.merged_into_id.is_(None))
        )).scalars().all())
        missing = [str(i) for i in ids if i not in valid]
        if missing:
            raise UnknownArtistError(f"unknown or merged artist: {missing[0]}")
    roles = {la.artist_id: la.role for la in live.artists}
    live.artists.clear()
    await session.flush()
    for pos, aid in enumerate(ids):
        live.artists.append(
            LiveSetArtist(artist_id=aid, position=pos, role=roles.get(aid, "main"))
        )


async def replace_tags(
    session: AsyncSession, live: LiveSet, tag_names: list[str]
) -> None:
    await session.execute(
        LiveSetTag.__table__.delete().where(LiveSetTag.live_set_id == live.id)
    )
    seen: set[uuid.UUID] = set()
    for raw in tag_names:
        name = raw.strip()
        if not name:
            continue
        base = slugify(name)
        # Names with no ASCII letters all slug to the fallback, so match those
        # by case-insensitive name instead of merging unrelated tags.
        if base == "item":
            cond = func.lower(Tag.name) == name.lower()
        else:
            cond = Tag.slug == base
        tag = (
            await session.execute(select(Tag).where(cond).limit(1))
        ).scalar_one_or_none()
        if tag is None:
            slug = await unique_slug(session, Tag, base, name=name)
            tag = Tag(name=name, slug=slug, kind="custom")
            session.add(tag)
            await session.flush()
        if tag.id in seen:
            continue
        seen.add(tag.id)
        session.add(LiveSetTag(live_set_id=live.id, tag_id=tag.id))
