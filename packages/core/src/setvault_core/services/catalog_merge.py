from __future__ import annotations

import uuid
from datetime import UTC, datetime

from pydantic_core import to_jsonable_python
from sqlalchemy import any_, delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_core.models.catalog import (
    Artist,
    LiveSet,
    LiveSetArtist,
    Party,
    Series,
    Venue,
)
from setvault_core.models.tracklist import (
    Label,
    Release,
    ReleaseTrack,
    Track,
    TracklistEntry,
)
from setvault_core.services.audit import log as audit_log
from setvault_core.services.catalog import EntityKind

_MODEL = {"artist": Artist, "venue": Venue, "party": Party, "series": Series}

# Scalar fields gap-filled from loser into survivor (survivor wins when non-empty).
_SCALAR = {
    "artist": ["country", "bio", "image_url"],
    "venue": ["kind", "city_or_area", "country", "lat", "lon", "capacity", "website"],
    "party": ["date", "description"],
    "series": ["description", "image_url"],
}


async def _repoint_artist(s, survivor_id, loser_id) -> dict:
    moved_join, deleted_join = [], []
    # LiveSetArtist: move loser->survivor, but drop rows that would collide on the
    # composite PK (the set already lists the survivor).
    rows = (await s.execute(
        select(LiveSetArtist).where(LiveSetArtist.artist_id == loser_id)
    )).scalars().all()
    existing = {
        r.live_set_id for r in (await s.execute(
            select(LiveSetArtist).where(LiveSetArtist.artist_id == survivor_id)
        )).scalars().all()
    }
    for r in rows:
        if r.live_set_id in existing:
            deleted_join.append([str(r.live_set_id), str(loser_id)])
            await s.delete(r)
        else:
            r.artist_id = survivor_id
            moved_join.append(str(r.live_set_id))
    await s.flush()
    moved_tracks, merged_tracks = await _merge_artist_tracks(s, survivor_id, loser_id)
    return {"moved": {"live_set_artists": moved_join, "tracks.primary_artist_id": moved_tracks},
            "deleted_join": deleted_join, "merged_tracks": merged_tracks}


def _track_key(t: Track) -> tuple[str, str | None]:
    return (t.title, t.mix_name)


async def _merge_artist_tracks(s, survivor_id, loser_id) -> tuple[list[str], list[dict]]:
    """Move the loser's tracks to the survivor. A loser track whose
    (title, mix_name) the survivor already has is folded into that track:
    tracklist entries, mashup references and release rows are repointed, the
    loser track is deleted and its snapshot is returned for unmerge."""
    survivor_tracks = (await s.execute(
        select(Track).where(Track.primary_artist_id == survivor_id)
        .order_by(Track.created_at, Track.id)
    )).scalars().all()
    by_key: dict[tuple, uuid.UUID] = {}
    for t in survivor_tracks:
        by_key.setdefault(_track_key(t), t.id)
    loser_tracks = (await s.execute(
        select(Track).where(Track.primary_artist_id == loser_id)
        .order_by(Track.created_at, Track.id)
    )).scalars().all()

    moved: list[uuid.UUID] = []
    merged: list[dict] = []
    for t in loser_tracks:
        target = by_key.get(_track_key(t))
        if target is None:
            moved.append(t.id)
            by_key[_track_key(t)] = t.id
            continue
        merged.append(await _fold_track(s, t, target))
    if moved:
        await s.execute(update(Track).where(Track.id.in_(moved))
                        .values(primary_artist_id=survivor_id))
    return [str(i) for i in moved], merged


async def _fold_track(s, track: Track, target_id: uuid.UUID) -> dict:
    snapshot = {c.key: getattr(track, c.key) for c in Track.__table__.columns}
    entries = [r[0] for r in (await s.execute(
        select(TracklistEntry.id).where(TracklistEntry.track_id == track.id)
    )).all()]
    if entries:
        await s.execute(update(TracklistEntry).where(TracklistEntry.id.in_(entries))
                        .values(track_id=target_id))
    mashups = (await s.execute(
        select(TracklistEntry.id, TracklistEntry.mashup_with)
        .where(any_(TracklistEntry.mashup_with) == track.id)
    )).all()
    if mashups:
        await s.execute(
            update(TracklistEntry).where(TracklistEntry.id.in_([m[0] for m in mashups]))
            .values(mashup_with=func.array_replace(TracklistEntry.mashup_with,
                                                   track.id, target_id))
        )
    target_releases = {r[0] for r in (await s.execute(
        select(ReleaseTrack.release_id).where(ReleaseTrack.track_id == target_id)
    )).all()}
    rel_moved, rel_deleted = [], []
    for rt in (await s.execute(
        select(ReleaseTrack).where(ReleaseTrack.track_id == track.id)
    )).scalars().all():
        if rt.release_id in target_releases:  # composite PK would collide
            rel_deleted.append([rt.release_id, rt.position])
            await s.delete(rt)
        else:
            rel_moved.append(rt.release_id)
            rt.track_id = target_id
    await s.flush()
    await s.execute(delete(Track).where(Track.id == track.id))
    s.expunge(track)
    return to_jsonable_python({
        "track": snapshot,
        "into": target_id,
        "entries": entries,
        "mashup_entries": [[m[0], list(m[1])] for m in mashups],
        "release_tracks_moved": rel_moved,
        "release_tracks_deleted": rel_deleted,
    })


async def _repoint_simple(s, *, loser_id, survivor_id, model, column) -> dict:
    ids = [r[0] for r in (await s.execute(
        select(model.id).where(column == loser_id)
    )).all()]
    if ids:
        await s.execute(update(model).where(model.id.in_(ids)).values({column.key: survivor_id}))
    return {"moved": {f"{model.__tablename__}.{column.key}": [str(i) for i in ids]}}


async def _repoint(s, kind, survivor_id, loser_id) -> dict:
    if kind == "artist":
        return await _repoint_artist(s, survivor_id, loser_id)
    if kind == "venue":
        a = await _repoint_simple(s, loser_id=loser_id, survivor_id=survivor_id,
                                  model=LiveSet, column=LiveSet.venue_id)
        b = await _repoint_simple(s, loser_id=loser_id, survivor_id=survivor_id,
                                  model=Party, column=Party.venue_id)
        return {"moved": {**a["moved"], **b["moved"]}}
    if kind == "party":
        return await _repoint_simple(s, loser_id=loser_id, survivor_id=survivor_id,
                                     model=LiveSet, column=LiveSet.party_id)
    if kind == "series":
        return await _repoint_simple(s, loser_id=loser_id, survivor_id=survivor_id,
                                     model=Party, column=Party.series_id)
    raise ValueError(f"unknown kind {kind}")


def _empty(v) -> bool:
    return v is None or v == "" or v == [] or v == {}


async def merge_entities(
    session: AsyncSession, *, kind: EntityKind,
    survivor_id: uuid.UUID, loser_id: uuid.UUID, actor_id: uuid.UUID | None,
):
    if survivor_id == loser_id:
        raise ValueError("cannot merge an entity into itself")
    if kind not in _MODEL:
        raise ValueError(f"unknown kind: {kind!r}")
    model = _MODEL[kind]
    survivor = await session.get(model, survivor_id)
    loser = await session.get(model, loser_id)
    if survivor is None or loser is None:
        raise ValueError("survivor or loser not found")
    if survivor.merged_into_id is not None or loser.merged_into_id is not None:
        raise ValueError("cannot merge a tombstoned entity")

    manifest = await _repoint(session, kind, survivor_id, loser_id)

    gap_filled = []
    for field in _SCALAR[kind]:
        if _empty(getattr(survivor, field)) and not _empty(getattr(loser, field)):
            setattr(survivor, field, getattr(loser, field))
            gap_filled.append(field)

    if kind == "artist":
        aliases = list(survivor.aliases or [])
        for extra in [loser.name, *(loser.aliases or [])]:
            if extra and extra not in aliases:
                aliases.append(extra)
        survivor.aliases = aliases
        survivor.external_ids = {**(loser.external_ids or {}), **(survivor.external_ids or {})}
        survivor.socials = {**(loser.socials or {}), **(survivor.socials or {})}

    manifest["survivor_id"] = str(survivor_id)
    manifest["gap_filled"] = gap_filled
    loser.merged_into_id = survivor_id
    loser.merged_at = datetime.now(UTC)
    loser.merge_manifest = manifest

    await audit_log(
        session, actor_user_id=actor_id, action=f"{kind}.merged",
        target_type=model.__name__, target_id=str(loser_id),
        after={"survivor_id": str(survivor_id), "manifest": manifest},
    )
    await session.flush()
    return survivor


async def unmerge_entity(
    session: AsyncSession, *, kind: EntityKind, loser_id: uuid.UUID, actor_id: uuid.UUID | None,
):
    model = _MODEL[kind]
    loser = await session.get(model, loser_id)
    if loser is None or loser.merged_into_id is None or loser.merge_manifest is None:
        raise ValueError("entity is not a merged tombstone")
    manifest = loser.merge_manifest

    for table_col, ids in manifest.get("moved", {}).items():
        if not ids:
            continue
        if table_col == "live_set_artists":
            await session.execute(
                update(LiveSetArtist)
                .where(LiveSetArtist.live_set_id.in_([uuid.UUID(i) for i in ids]),
                       LiveSetArtist.artist_id == uuid.UUID(manifest["survivor_id"]))
                .values(artist_id=loser_id)
            )
        elif table_col == "tracks.primary_artist_id":
            await session.execute(update(Track).where(Track.id.in_([uuid.UUID(i) for i in ids]))
                                  .values(primary_artist_id=loser_id))
        elif table_col == "live_sets.venue_id":
            await session.execute(update(LiveSet).where(LiveSet.id.in_([uuid.UUID(i) for i in ids]))
                                  .values(venue_id=loser_id))
        elif table_col == "parties.venue_id":
            await session.execute(update(Party).where(Party.id.in_([uuid.UUID(i) for i in ids]))
                                  .values(venue_id=loser_id))
        elif table_col == "live_sets.party_id":
            await session.execute(update(LiveSet).where(LiveSet.id.in_([uuid.UUID(i) for i in ids]))
                                  .values(party_id=loser_id))
        elif table_col == "parties.series_id":
            await session.execute(update(Party).where(Party.id.in_([uuid.UUID(i) for i in ids]))
                                  .values(series_id=loser_id))
    # Reverse order: each fold recorded the mashup arrays as it found them,
    # after earlier folds had already rewritten them.
    for folded in reversed(manifest.get("merged_tracks", [])):
        await _restore_track(session, folded)
    # recreate join rows that were dropped on PK collision
    for ls_id, _aid in manifest.get("deleted_join", []):
        session.add(LiveSetArtist(live_set_id=uuid.UUID(ls_id), artist_id=loser_id))

    loser.merged_into_id = None
    loser.merged_at = None
    loser.merge_manifest = None
    await audit_log(session, actor_user_id=actor_id, action=f"{kind}.unmerged",
                    target_type=model.__name__, target_id=str(loser_id))
    await session.flush()
    return loser


_TRACK_UUID_COLS = {"id", "primary_artist_id", "label_id", "release_id"}
_TRACK_DT_COLS = {"created_at", "updated_at"}


async def _restore_track(session, folded: dict) -> None:
    """Undo _fold_track: recreate the deleted loser track and move back the
    references that were repointed to the survivor's track."""
    values = {}
    for col, v in folded["track"].items():
        if v is not None and col in _TRACK_UUID_COLS:
            v = uuid.UUID(v)
        elif v is not None and col in _TRACK_DT_COLS:
            v = datetime.fromisoformat(v)
        values[col] = v
    # The label/release may have been deleted since the merge: drop the link
    # rather than fail the whole unmerge on a dangling FK.
    if values.get("label_id") is not None and await session.get(Label, values["label_id"]) is None:
        values["label_id"] = None
    if (values.get("release_id") is not None
            and await session.get(Release, values["release_id"]) is None):
        values["release_id"] = None
    track_id, into = values["id"], uuid.UUID(folded["into"])
    await session.execute(insert(Track).values(**values))
    entries = [uuid.UUID(i) for i in folded.get("entries", [])]
    if entries:
        await session.execute(
            update(TracklistEntry)
            .where(TracklistEntry.id.in_(entries), TracklistEntry.track_id == into)
            .values(track_id=track_id)
        )
    for entry_id, original in folded.get("mashup_entries", []):
        await session.execute(
            update(TracklistEntry).where(TracklistEntry.id == uuid.UUID(entry_id))
            .values(mashup_with=[uuid.UUID(i) for i in original])
        )
    moved = [uuid.UUID(i) for i in folded.get("release_tracks_moved", [])]
    if moved:
        await session.execute(
            update(ReleaseTrack)
            .where(ReleaseTrack.release_id.in_(moved), ReleaseTrack.track_id == into)
            .values(track_id=track_id)
        )
    for release_id, position in folded.get("release_tracks_deleted", []):
        rid = uuid.UUID(release_id)
        if await session.get(Release, rid) is None:
            continue  # release deleted since the merge
        await session.execute(insert(ReleaseTrack).values(
            release_id=rid, track_id=track_id, position=position))
