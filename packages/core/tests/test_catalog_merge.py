# packages/core/tests/test_catalog_merge.py
import os
import uuid

import pytest
from setvault_core.db import init_engine
from setvault_core.models.catalog import (
    Artist,
    LiveSet,
    LiveSetArtist,
    MediaRoot,
    Party,
    Series,
    Venue,
)
from setvault_core.models.identity import User
from setvault_core.models.monitors import Monitor
from setvault_core.models.tracklist import Label, Release, ReleaseTrack, Track, TracklistEntry
from setvault_core.services.catalog_merge import merge_entities, unmerge_entity
from setvault_core.services.passwords import hash_password
from sqlalchemy import select


@pytest.fixture(autouse=True)
def _engine():
    init_engine(os.environ["TEST_DATABASE_URL"])


async def _scaffold(s):
    root = MediaRoot(name=f"r-{uuid.uuid4().hex[:6]}", host_path="/srv/test-media")
    s.add(root)
    await s.flush()
    u = User(email=f"u-{uuid.uuid4().hex[:6]}@x.test", username=f"u{uuid.uuid4().hex[:6]}",
             display_name="u", password_hash=hash_password("aaaaaaaa"))
    s.add(u)
    await s.flush()
    return root.id, u.id


async def test_merge_artist_repoints_refs_and_tombstones_loser(session):
    s = session
    root_id, uid = await _scaffold(s)
    survivor = Artist(name="DJ X", slug=f"x-{uuid.uuid4().hex[:6]}", bio="canonical")
    loser = Artist(name="DJ X (alt)", slug=f"xa-{uuid.uuid4().hex[:6]}", country="BE")
    s.add_all([survivor, loser])
    await s.flush()

    ls = LiveSet(slug=f"s-{uuid.uuid4().hex[:8]}", title="t", media_root_id=root_id,
                 audio_path="a/b.flac", status="published", source_type="upload", uploaded_by=uid)
    s.add(ls)
    await s.flush()
    s.add(LiveSetArtist(live_set_id=ls.id, artist_id=loser.id, position=0))
    track = Track(title="T", primary_artist_id=loser.id)
    s.add(track)
    await s.commit()
    survivor_id, loser_id, ls_id, track_id = survivor.id, loser.id, ls.id, track.id

    await merge_entities(s, kind="artist", survivor_id=survivor_id, loser_id=loser_id, actor_id=uid)
    await s.commit()

    # references now point at survivor
    lsa = (await s.execute(
        LiveSetArtist.__table__.select().where(LiveSetArtist.live_set_id == ls_id)
    )).first()
    assert lsa.artist_id == survivor_id
    assert (await s.get(Track, track_id)).primary_artist_id == survivor_id
    # loser tombstoned
    dead = await s.get(Artist, loser_id)
    assert dead.merged_into_id == survivor_id and dead.merged_at is not None
    # gap-fill: survivor had no country, takes loser's
    surv = await s.get(Artist, survivor_id)
    assert surv.country == "BE"
    assert surv.bio == "canonical"  # survivor's own non-empty field wins
    # loser name folded into survivor aliases
    assert "DJ X (alt)" in surv.aliases


async def test_merge_artist_dedupes_join_pk_collision(session):
    s = session
    root_id, uid = await _scaffold(s)
    survivor = Artist(name="A", slug=f"a-{uuid.uuid4().hex[:6]}")
    loser = Artist(name="A dup", slug=f"ad-{uuid.uuid4().hex[:6]}")
    s.add_all([survivor, loser])
    await s.flush()
    ls = LiveSet(slug=f"s-{uuid.uuid4().hex[:8]}", title="t", media_root_id=root_id,
                 audio_path="a/b.flac", status="published", source_type="upload", uploaded_by=uid)
    s.add(ls)
    await s.flush()
    # BOTH artists on the same set -> merging would collide on (live_set_id, artist_id)
    s.add(LiveSetArtist(live_set_id=ls.id, artist_id=survivor.id, position=0))
    s.add(LiveSetArtist(live_set_id=ls.id, artist_id=loser.id, position=1))
    await s.commit()
    sid, lid, ls_id = survivor.id, loser.id, ls.id

    await merge_entities(s, kind="artist", survivor_id=sid, loser_id=lid, actor_id=uid)
    await s.commit()

    rows = (await s.execute(
        LiveSetArtist.__table__.select().where(LiveSetArtist.live_set_id == ls_id)
    )).all()
    artist_ids = {r.artist_id for r in rows}
    assert artist_ids == {sid}  # the colliding loser row was dropped, not duplicated


async def test_merge_rejects_same_id(session):
    s = session
    a = Artist(name="Z", slug=f"z-{uuid.uuid4().hex[:6]}")
    s.add(a)
    await s.commit()
    with pytest.raises(ValueError):
        await merge_entities(s, kind="artist", survivor_id=a.id, loser_id=a.id, actor_id=None)


async def test_merge_rejects_unknown_kind(session):
    s = session
    a = Artist(name="K", slug=f"k-{uuid.uuid4().hex[:6]}")
    b = Artist(name="K2", slug=f"k2-{uuid.uuid4().hex[:6]}")
    s.add_all([a, b])
    await s.commit()
    with pytest.raises(ValueError):
        await merge_entities(s, kind="bogus", survivor_id=a.id, loser_id=b.id, actor_id=None)


async def test_merge_venue_repoints_sets_and_parties(session):
    s = session
    root_id, uid = await _scaffold(s)
    keep = Venue(name="Club", slug=f"c-{uuid.uuid4().hex[:6]}", kind="club")
    dup = Venue(name="Club dup", slug=f"cd-{uuid.uuid4().hex[:6]}", kind="club")
    s.add_all([keep, dup])
    await s.flush()
    ls = LiveSet(slug=f"s-{uuid.uuid4().hex[:8]}", title="t", media_root_id=root_id,
                 audio_path="a/b.flac", status="published", source_type="upload",
                 uploaded_by=uid, venue_id=dup.id)
    party = Party(name="P", slug=f"p-{uuid.uuid4().hex[:6]}", venue_id=dup.id)
    s.add_all([ls, party])
    await s.commit()
    keep_id, dup_id, ls_id, party_id = keep.id, dup.id, ls.id, party.id

    await merge_entities(s, kind="venue", survivor_id=keep_id, loser_id=dup_id, actor_id=uid)
    await s.commit()
    assert (await s.get(LiveSet, ls_id)).venue_id == keep_id
    assert (await s.get(Party, party_id)).venue_id == keep_id
    assert (await s.get(Venue, dup_id)).merged_into_id == keep_id


async def test_merge_series_repoints_parties(session):
    s = session
    keep = Series(name="Ser", slug=f"ser-{uuid.uuid4().hex[:6]}")
    dup = Series(name="Ser dup", slug=f"serd-{uuid.uuid4().hex[:6]}")
    s.add_all([keep, dup])
    await s.flush()
    party = Party(name="P", slug=f"p-{uuid.uuid4().hex[:6]}", series_id=dup.id)
    s.add(party)
    await s.commit()
    keep_id, dup_id, party_id = keep.id, dup.id, party.id

    await merge_entities(s, kind="series", survivor_id=keep_id, loser_id=dup_id, actor_id=None)
    await s.commit()
    assert (await s.get(Party, party_id)).series_id == keep_id
    assert (await s.get(Series, dup_id)).merged_into_id == keep_id


async def test_unmerge_restores_references(session):
    s = session
    root_id, uid = await _scaffold(s)
    survivor = Artist(name="DJ X", slug=f"x-{uuid.uuid4().hex[:6]}")
    loser = Artist(name="DJ X alt", slug=f"xa-{uuid.uuid4().hex[:6]}")
    s.add_all([survivor, loser])
    await s.flush()
    ls = LiveSet(slug=f"s-{uuid.uuid4().hex[:8]}", title="t", media_root_id=root_id,
                 audio_path="a/b.flac", status="published", source_type="upload", uploaded_by=uid)
    s.add(ls)
    await s.flush()
    s.add(LiveSetArtist(live_set_id=ls.id, artist_id=loser.id, position=0))
    await s.commit()
    sid, lid, ls_id = survivor.id, loser.id, ls.id

    await merge_entities(s, kind="artist", survivor_id=sid, loser_id=lid, actor_id=uid)
    await s.commit()
    await unmerge_entity(s, kind="artist", loser_id=lid, actor_id=uid)
    await s.commit()

    revived = await s.get(Artist, lid)
    assert revived.merged_into_id is None and revived.merge_manifest is None
    lsa = (await s.execute(
        LiveSetArtist.__table__.select().where(LiveSetArtist.live_set_id == ls_id)
    )).first()
    assert lsa.artist_id == lid  # reference moved back to the revived entity


async def test_unmerge_venue_restores_references(session):
    s = session
    root_id, uid = await _scaffold(s)
    keep = Venue(name="Club", slug=f"c-{uuid.uuid4().hex[:6]}", kind="club")
    dup = Venue(name="Club dup", slug=f"cd-{uuid.uuid4().hex[:6]}", kind="club")
    s.add_all([keep, dup])
    await s.flush()
    ls = LiveSet(slug=f"s-{uuid.uuid4().hex[:8]}", title="t", media_root_id=root_id,
                 audio_path="a/b.flac", status="published", source_type="upload",
                 uploaded_by=uid, venue_id=dup.id)
    party = Party(name="P", slug=f"p-{uuid.uuid4().hex[:6]}", venue_id=dup.id)
    s.add_all([ls, party])
    await s.commit()
    keep_id, dup_id, ls_id, party_id = keep.id, dup.id, ls.id, party.id

    await merge_entities(s, kind="venue", survivor_id=keep_id, loser_id=dup_id, actor_id=uid)
    await s.commit()
    await unmerge_entity(s, kind="venue", loser_id=dup_id, actor_id=uid)
    await s.commit()

    revived = await s.get(Venue, dup_id)
    assert revived.merged_into_id is None and revived.merge_manifest is None
    # both the LiveSet.venue_id and Party.venue_id references move back to the revived venue
    assert (await s.get(LiveSet, ls_id)).venue_id == dup_id
    assert (await s.get(Party, party_id)).venue_id == dup_id


async def test_unmerge_recreates_dropped_join(session):
    s = session
    root_id, uid = await _scaffold(s)
    # both artists on one set -> merge drops the loser join row (PK collision, deleted_join)
    survivor = Artist(name="A", slug=f"a-{uuid.uuid4().hex[:6]}")
    loser = Artist(name="A dup", slug=f"ad-{uuid.uuid4().hex[:6]}")
    s.add_all([survivor, loser])
    await s.flush()
    ls = LiveSet(slug=f"s-{uuid.uuid4().hex[:8]}", title="t", media_root_id=root_id,
                 audio_path="a/b.flac", status="published", source_type="upload", uploaded_by=uid)
    s.add(ls)
    await s.flush()
    s.add(LiveSetArtist(live_set_id=ls.id, artist_id=survivor.id, position=0))
    s.add(LiveSetArtist(live_set_id=ls.id, artist_id=loser.id, position=1))
    await s.commit()
    sid, lid, ls_id = survivor.id, loser.id, ls.id

    await merge_entities(s, kind="artist", survivor_id=sid, loser_id=lid, actor_id=uid)
    await s.commit()
    # after merge only the survivor row remains on the set
    rows = (await s.execute(
        LiveSetArtist.__table__.select().where(LiveSetArtist.live_set_id == ls_id)
    )).all()
    assert {r.artist_id for r in rows} == {sid}

    await unmerge_entity(s, kind="artist", loser_id=lid, actor_id=uid)
    await s.commit()
    # the dropped loser join row is recreated -> both artists back on the set
    rows = (await s.execute(
        LiveSetArtist.__table__.select().where(LiveSetArtist.live_set_id == ls_id)
    )).all()
    assert {r.artist_id for r in rows} == {sid, lid}


async def test_artist_merge_merges_duplicate_tracks(session):
    s = session
    root_id, uid = await _scaffold(s)
    survivor = Artist(name="M", slug=f"m-{uuid.uuid4().hex[:6]}")
    loser = Artist(name="M dup", slug=f"md-{uuid.uuid4().hex[:6]}")
    s.add_all([survivor, loser])
    await s.flush()
    keep = Track(title="Song", primary_artist_id=survivor.id)
    keep_mix = Track(title="Song", mix_name="Dub", primary_artist_id=survivor.id)
    dup = Track(title="Song", primary_artist_id=loser.id, bpm=128.0, external_ids={"x": "1"})
    dup_mix = Track(title="Song", mix_name="Dub", primary_artist_id=loser.id)
    other = Track(title="Other", mix_name="Extended", primary_artist_id=loser.id)
    s.add_all([keep, keep_mix, dup, dup_mix, other])
    await s.flush()
    ls = LiveSet(slug=f"s-{uuid.uuid4().hex[:8]}", title="t", media_root_id=root_id,
                 audio_path="a/b.flac", status="published", source_type="upload", uploaded_by=uid)
    s.add(ls)
    await s.flush()
    e1 = TracklistEntry(live_set_id=ls.id, position=0, start_seconds=0, raw_label="a",
                        track_id=dup.id, created_by=uid)
    e2 = TracklistEntry(live_set_id=ls.id, position=1, start_seconds=60, raw_label="b",
                        track_id=other.id, mashup_with=[dup.id], created_by=uid)
    e3 = TracklistEntry(live_set_id=ls.id, position=2, start_seconds=120, raw_label="c",
                        track_id=dup_mix.id, created_by=uid)
    both = Release(title="Both")      # holds keep AND dup -> PK collision on repoint
    only_dup = Release(title="Dup")   # holds dup only -> simple repoint
    s.add_all([e1, e2, e3, both, only_dup])
    await s.flush()
    s.add_all([
        ReleaseTrack(release_id=both.id, track_id=keep.id, position=1),
        ReleaseTrack(release_id=both.id, track_id=dup.id, position=2),
        ReleaseTrack(release_id=only_dup.id, track_id=dup.id, position=3),
    ])
    await s.commit()
    sid, lid = survivor.id, loser.id
    keep_id, keep_mix_id, dup_id, dup_mix_id, other_id = (
        keep.id, keep_mix.id, dup.id, dup_mix.id, other.id)
    e1_id, e2_id, e3_id, both_id, only_id = e1.id, e2.id, e3.id, both.id, only_dup.id

    await merge_entities(s, kind="artist", survivor_id=sid, loser_id=lid, actor_id=uid)
    await s.commit()
    s.expire_all()

    tracks = (await s.execute(select(Track).where(Track.primary_artist_id == sid))).scalars().all()
    keys = [(t.title, t.mix_name) for t in tracks]
    assert sorted(keys, key=str) == sorted(
        [("Song", None), ("Song", "Dub"), ("Other", "Extended")], key=str)
    assert {t.id for t in tracks} == {keep_id, keep_mix_id, other_id}
    assert await s.get(Track, dup_id) is None
    assert await s.get(Track, dup_mix_id) is None
    assert (await s.get(TracklistEntry, e1_id)).track_id == keep_id
    assert (await s.get(TracklistEntry, e2_id)).mashup_with == [keep_id]
    assert (await s.get(TracklistEntry, e3_id)).track_id == keep_mix_id
    rts = {(r.release_id, r.track_id, r.position) for r in (await s.execute(
        select(ReleaseTrack).where(ReleaseTrack.release_id.in_([both_id, only_id]))
    )).scalars().all()}
    assert rts == {(both_id, keep_id, 1), (only_id, keep_id, 3)}

    await unmerge_entity(s, kind="artist", loser_id=lid, actor_id=uid)
    await s.commit()
    s.expire_all()

    restored = await s.get(Track, dup_id)
    assert restored is not None
    assert restored.primary_artist_id == lid
    assert restored.title == "Song" and restored.mix_name is None
    assert restored.bpm == 128.0 and restored.external_ids == {"x": "1"}
    assert (await s.get(Track, dup_mix_id)).primary_artist_id == lid
    assert (await s.get(Track, other_id)).primary_artist_id == lid
    assert (await s.get(Track, keep_id)).primary_artist_id == sid
    assert (await s.get(TracklistEntry, e1_id)).track_id == dup_id
    assert (await s.get(TracklistEntry, e2_id)).mashup_with == [dup_id]
    assert (await s.get(TracklistEntry, e3_id)).track_id == dup_mix_id
    rts = {(r.release_id, r.track_id, r.position) for r in (await s.execute(
        select(ReleaseTrack).where(ReleaseTrack.release_id.in_([both_id, only_id]))
    )).scalars().all()}
    assert rts == {(both_id, keep_id, 1), (both_id, dup_id, 2), (only_id, dup_id, 3)}


async def _two_artists_and_set(s):
    root_id, uid = await _scaffold(s)
    survivor = Artist(name="S", slug=f"s-{uuid.uuid4().hex[:6]}")
    loser = Artist(name="S dup", slug=f"sd-{uuid.uuid4().hex[:6]}")
    s.add_all([survivor, loser])
    await s.flush()
    ls = LiveSet(slug=f"s-{uuid.uuid4().hex[:8]}", title="t", media_root_id=root_id,
                 audio_path="a/b.flac", status="published", source_type="upload", uploaded_by=uid)
    s.add(ls)
    await s.flush()
    return survivor, loser, ls, uid


async def test_unmerge_restores_mashup_with_several_folded_tracks(session):
    s = session
    survivor, loser, ls, uid = await _two_artists_and_set(s)
    ka = Track(title="A", primary_artist_id=survivor.id)
    kb = Track(title="B", primary_artist_id=survivor.id)
    da = Track(title="A", primary_artist_id=loser.id)
    db = Track(title="B", primary_artist_id=loser.id)
    s.add_all([ka, kb, da, db])
    await s.flush()
    e = TracklistEntry(live_set_id=ls.id, position=0, start_seconds=0, raw_label="m",
                       mashup_with=[da.id, db.id], created_by=uid)
    s.add(e)
    await s.commit()
    sid, lid, e_id = survivor.id, loser.id, e.id
    ka_id, kb_id, da_id, db_id = ka.id, kb.id, da.id, db.id

    await merge_entities(s, kind="artist", survivor_id=sid, loser_id=lid, actor_id=uid)
    await s.commit()
    s.expire_all()
    assert (await s.get(TracklistEntry, e_id)).mashup_with == [ka_id, kb_id]

    await unmerge_entity(s, kind="artist", loser_id=lid, actor_id=uid)
    await s.commit()
    s.expire_all()
    assert (await s.get(TracklistEntry, e_id)).mashup_with == [da_id, db_id]


async def test_unmerge_tolerates_deleted_label_and_release(session):
    s = session
    survivor, loser, _ls, uid = await _two_artists_and_set(s)
    label = Label(name="L", slug=f"l-{uuid.uuid4().hex[:6]}")
    rel = Release(title="R")
    s.add_all([label, rel])
    await s.flush()
    keep = Track(title="X", primary_artist_id=survivor.id)
    dup = Track(title="X", primary_artist_id=loser.id, label_id=label.id, release_id=rel.id)
    s.add_all([keep, dup])
    await s.flush()
    s.add_all([ReleaseTrack(release_id=rel.id, track_id=keep.id, position=0),
               ReleaseTrack(release_id=rel.id, track_id=dup.id, position=1)])
    await s.commit()
    sid, lid, dup_id = survivor.id, loser.id, dup.id

    await merge_entities(s, kind="artist", survivor_id=sid, loser_id=lid, actor_id=uid)
    await s.commit()
    await s.delete(await s.get(Release, rel.id))
    await s.delete(await s.get(Label, label.id))
    await s.commit()

    await unmerge_entity(s, kind="artist", loser_id=lid, actor_id=uid)
    await s.commit()
    s.expire_all()
    restored = await s.get(Track, dup_id)
    assert restored.primary_artist_id == lid
    assert restored.label_id is None and restored.release_id is None
    assert (await s.execute(
        select(ReleaseTrack).where(ReleaseTrack.track_id == dup_id)
    )).scalars().all() == []


def _entity(kind: str, name: str):
    slug = f"{kind}-{uuid.uuid4().hex[:8]}"
    if kind == "venue":
        return Venue(name=name, slug=slug, kind="club")
    return {"artist": Artist, "party": Party}[kind](name=name, slug=slug)


async def _user(s) -> uuid.UUID:
    u = User(email=f"u-{uuid.uuid4().hex[:6]}@x.test", username=f"u{uuid.uuid4().hex[:6]}",
             display_name="u", password_hash=hash_password("aaaaaaaa"))
    s.add(u)
    await s.flush()
    return u.id


def _monitor(owner, kind, entity_id, query="q") -> Monitor:
    return Monitor(owner_user_id=owner, kind="query", query_text=query,
                   catalog_kind=kind, catalog_id=entity_id)


@pytest.mark.parametrize("kind", ["artist", "party", "venue"])
async def test_merge_repoints_monitor_to_survivor(session, kind):
    s = session
    uid = await _user(s)
    survivor, loser = _entity(kind, "Keep"), _entity(kind, "Lose")
    s.add_all([survivor, loser])
    await s.flush()
    m = _monitor(uid, kind, loser.id, query="Lose tuned")
    s.add(m)
    await s.commit()
    sid, lid, mid = survivor.id, loser.id, m.id

    await merge_entities(s, kind=kind, survivor_id=sid, loser_id=lid, actor_id=uid)
    await s.commit()
    s.expire_all()
    moved = await s.get(Monitor, mid)
    assert (moved.catalog_kind, moved.catalog_id) == (kind, sid)
    assert moved.query_text == "Lose tuned"  # the user's query is kept

    await unmerge_entity(s, kind=kind, loser_id=lid, actor_id=uid)
    await s.commit()
    s.expire_all()
    assert (await s.get(Monitor, mid)).catalog_id == lid


async def test_merge_drops_loser_monitor_when_survivor_has_one(session):
    s = session
    both, only_loser, revive = await _user(s), await _user(s), await _user(s)
    survivor, loser = _entity("artist", "Keep"), _entity("artist", "Lose")
    s.add_all([survivor, loser])
    await s.flush()
    keep = _monitor(both, "artist", survivor.id, query="Keep")
    drop = _monitor(both, "artist", loser.id, query="Lose")
    drop.per_poll_cap, drop.enabled = 9, False
    move = _monitor(only_loser, "artist", loser.id, query="Lose")
    # A paused survivor monitor plus an active loser one: monitoring must go on.
    paused = _monitor(revive, "artist", survivor.id, query="Keep")
    paused.enabled = False
    active = _monitor(revive, "artist", loser.id, query="Lose")
    s.add_all([keep, drop, move, paused, active])
    await s.commit()
    sid, lid = survivor.id, loser.id
    keep_id, drop_id, move_id = keep.id, drop.id, move.id
    paused_id, active_id = paused.id, active.id

    await merge_entities(s, kind="artist", survivor_id=sid, loser_id=lid, actor_id=both)
    await s.commit()
    s.expire_all()
    assert await s.get(Monitor, drop_id) is None
    assert await s.get(Monitor, active_id) is None
    assert (await s.get(Monitor, paused_id)).enabled is True
    assert (await s.get(Monitor, keep_id)).enabled is True  # a paused loser changes nothing
    assert (await s.get(Monitor, keep_id)).catalog_id == sid
    assert (await s.get(Monitor, move_id)).catalog_id == sid
    linked = (await s.execute(select(Monitor).where(
        Monitor.catalog_kind == "artist", Monitor.catalog_id == sid,
        Monitor.owner_user_id == both,
    ))).scalars().all()
    assert [x.id for x in linked] == [keep_id]

    # Unmerge brings the dropped monitor back as it was.
    await unmerge_entity(s, kind="artist", loser_id=lid, actor_id=both)
    await s.commit()
    s.expire_all()
    restored = await s.get(Monitor, drop_id)
    assert restored is not None
    assert (restored.owner_user_id, restored.catalog_id, restored.query_text) == (both, lid, "Lose")
    assert (restored.per_poll_cap, restored.enabled) == (9, False)
    assert (await s.get(Monitor, move_id)).catalog_id == lid
    assert (await s.get(Monitor, keep_id)).catalog_id == sid
    assert (await s.get(Monitor, paused_id)).enabled is False  # back as it was
    assert (await s.get(Monitor, active_id)).enabled is True


async def test_rename_keeps_monitor_query(session):
    """Renaming a monitored entity leaves the monitor's (maybe tuned) query alone."""
    s = session
    uid = await _user(s)
    artist = _entity("artist", "Old Name")
    s.add(artist)
    await s.flush()
    m = _monitor(uid, "artist", artist.id, query="Old Name live")
    s.add(m)
    await s.commit()

    mid, aid = m.id, artist.id

    artist.name = "New Name"
    await s.commit()
    s.expire_all()
    m = await s.get(Monitor, mid)
    assert m.query_text == "Old Name live"
    assert m.catalog_id == aid
