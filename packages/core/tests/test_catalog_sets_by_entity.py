# packages/core/tests/test_catalog_sets_by_entity.py
import os
import uuid

import pytest
from setvault_core.db import init_engine
from setvault_core.models.catalog import Artist, LiveSet, LiveSetArtist, Party, Series, Venue
from setvault_core.models.identity import User
from setvault_core.services.catalog import list_sets_for_entity
from setvault_core.services.passwords import hash_password


@pytest.fixture(autouse=True)
def _engine():
    init_engine(os.environ["TEST_DATABASE_URL"])


async def _user(s) -> uuid.UUID:
    u = User(email=f"u-{uuid.uuid4().hex[:6]}@x.test", username=f"u{uuid.uuid4().hex[:6]}",
             display_name="u", password_hash=hash_password("aaaaaaaa"))
    s.add(u)
    await s.flush()
    return u.id


async def _set(s, *, uploader, root_id, venue_id=None, party_id=None, artist_id=None):
    ls = LiveSet(slug=f"s-{uuid.uuid4().hex[:8]}", title="t", media_root_id=root_id,
                 audio_path="a/b.flac", status="published", source_type="upload",
                 uploaded_by=uploader, venue_id=venue_id, party_id=party_id)
    s.add(ls)
    await s.flush()
    if artist_id:
        s.add(LiveSetArtist(live_set_id=ls.id, artist_id=artist_id, position=0))
        await s.flush()
    return ls.id


async def test_lists_sets_for_each_entity_kind(session):
    s = session
    from setvault_core.models.catalog import MediaRoot
    root = MediaRoot(name=f"r-{uuid.uuid4().hex[:6]}", host_path="/srv/test-media")
    s.add(root)
    await s.flush()
    uploader = await _user(s)

    artist = Artist(name="DJ A", slug=f"dj-a-{uuid.uuid4().hex[:6]}")
    venue = Venue(name="V", slug=f"v-{uuid.uuid4().hex[:6]}", kind="club")
    series = Series(name="Ser", slug=f"ser-{uuid.uuid4().hex[:6]}")
    s.add_all([artist, venue, series])
    await s.flush()
    party = Party(
        name="P", slug=f"p-{uuid.uuid4().hex[:6]}", series_id=series.id, venue_id=venue.id,
    )
    s.add(party)
    await s.flush()

    a_set = await _set(s, uploader=uploader, root_id=root.id, artist_id=artist.id)
    v_set = await _set(s, uploader=uploader, root_id=root.id, venue_id=venue.id)
    p_set = await _set(s, uploader=uploader, root_id=root.id, party_id=party.id)
    await s.commit()

    artist_sets, _ = await list_sets_for_entity(s, kind="artist", entity_id=artist.id)
    assert [x.id for x in artist_sets] == [a_set]
    venue_sets, _ = await list_sets_for_entity(s, kind="venue", entity_id=venue.id)
    assert [x.id for x in venue_sets] == [v_set]
    party_sets, _ = await list_sets_for_entity(s, kind="party", entity_id=party.id)
    assert [x.id for x in party_sets] == [p_set]
    # series: sets whose party belongs to the series
    series_sets, _ = await list_sets_for_entity(s, kind="series", entity_id=series.id)
    assert [x.id for x in series_sets] == [p_set]


async def test_excludes_soft_deleted_and_unpublished(session):
    s = session
    from datetime import UTC, datetime

    from setvault_core.models.catalog import MediaRoot
    root = MediaRoot(name=f"r-{uuid.uuid4().hex[:6]}", host_path="/srv/test-media")
    s.add(root)
    await s.flush()
    uploader = await _user(s)
    artist = Artist(name="DJ B", slug=f"dj-b-{uuid.uuid4().hex[:6]}")
    s.add(artist)
    await s.flush()
    live_id = await _set(s, uploader=uploader, root_id=root.id, artist_id=artist.id)
    deleted_id = await _set(s, uploader=uploader, root_id=root.id, artist_id=artist.id)
    deleted = await s.get(LiveSet, deleted_id)
    deleted.deleted_at = datetime.now(UTC)
    await s.commit()

    rows, total = await list_sets_for_entity(s, kind="artist", entity_id=artist.id)
    assert [x.id for x in rows] == [live_id]
    assert total == 1
