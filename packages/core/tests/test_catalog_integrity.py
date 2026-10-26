# packages/core/tests/test_catalog_integrity.py
"""Audit payload encoding, enrichment lookups and unique slugs (P1 #22/#23)."""
import os
import re
import uuid
from datetime import date, datetime

import pytest
from setvault_core.db import init_engine
from setvault_core.models.catalog import Artist
from setvault_core.models.system import AuditEvent
from setvault_core.models.tracklist import Track, TracklistEntry
from setvault_core.services.audit import log as audit_log
from setvault_core.services.catalog import slugify, unique_slug
from setvault_core.services.enrichment import accept_candidate
from sqlalchemy import select


@pytest.fixture(autouse=True)
def _engine():
    init_engine(os.environ["TEST_DATABASE_URL"])


async def test_audit_log_encodes_dates_and_uuids(session):
    s = session
    some_id = uuid.uuid4()
    when = datetime(2026, 1, 2, 3, 4, 5)
    event = await audit_log(
        s, actor_user_id=None, action="test.encoded",
        before={"date": date(2026, 1, 1)},
        after={"date": date(2026, 1, 2), "id": some_id, "at": when, "nested": [some_id]},
    )
    await s.flush()  # a raw date/UUID in JSONB would raise here
    row = (await s.execute(select(AuditEvent).where(AuditEvent.id == event.id))).scalar_one()
    assert row.before == {"date": "2026-01-01"}
    assert row.after["date"] == "2026-01-02"
    assert row.after["id"] == str(some_id)
    assert row.after["nested"] == [str(some_id)]
    assert row.after["at"].startswith("2026-01-02T03:04:05")


async def test_accept_candidate_tolerates_duplicate_tracks(session_with_set):
    s, _ls_id, entry_ids = session_with_set
    name = f"Dup Artist {uuid.uuid4().hex[:6]}"
    artist = Artist(name=name, slug=slugify(name))
    s.add(artist)
    await s.commit()
    first = Track(title="Same Song", primary_artist_id=artist.id)
    s.add(first)
    await s.commit()  # separate transactions -> distinct created_at
    second = Track(title="Same Song", primary_artist_id=artist.id)
    s.add(second)
    await s.commit()

    entry = await s.get(TracklistEntry, uuid.UUID(entry_ids[0]))
    track = await accept_candidate(
        s, entry, title="Same Song", artist_name=name, external_ids={},
        confirmed_via_acoustid=False, field_priority={}, providers=[],
    )
    assert track.id == first.id
    assert entry.track_id == first.id


async def test_enrichment_lookup_skips_tombstone(session_with_set):
    s, _ls_id, entry_ids = session_with_set
    name = f"Ghost {uuid.uuid4().hex[:6]}"
    survivor = Artist(name=f"{name} canonical", slug=slugify(f"{name} canonical"))
    s.add(survivor)
    await s.flush()
    tomb = Artist(name=name, slug=slugify(name), merged_into_id=survivor.id)
    s.add(tomb)
    await s.commit()

    entry = await s.get(TracklistEntry, uuid.UUID(entry_ids[0]))
    track = await accept_candidate(
        s, entry, title="Haunted", artist_name=name, external_ids={},
        confirmed_via_acoustid=False, field_priority={}, providers=[],
    )
    # never attached to the tombstone, never a re-created duplicate: the survivor
    assert track.primary_artist_id == survivor.id
    assert (await s.execute(
        select(Artist).where(Artist.name == name, Artist.merged_into_id.is_(None))
    )).scalars().first() is None


async def test_enrichment_lookup_follows_merge_chain(session_with_set):
    s, _ls_id, entry_ids = session_with_set
    tag = uuid.uuid4().hex[:6]
    final = Artist(name=f"Final {tag}", slug=f"final-{tag}")
    s.add(final)
    await s.flush()
    middle = Artist(name=f"Middle {tag}", slug=f"middle-{tag}", merged_into_id=final.id)
    s.add(middle)
    await s.flush()
    first = Artist(name=f"First {tag}", slug=f"first-{tag}", merged_into_id=middle.id)
    s.add(first)
    await s.commit()

    entry = await s.get(TracklistEntry, uuid.UUID(entry_ids[0]))
    track = await accept_candidate(
        s, entry, title="Chain", artist_name=f"First {tag}", external_ids={},
        confirmed_via_acoustid=False, field_priority={}, providers=[],
    )
    assert track.primary_artist_id == final.id


async def test_enrichment_lookup_merge_cycle_guard(session_with_set):
    s, _ls_id, entry_ids = session_with_set
    tag = uuid.uuid4().hex[:6]
    a = Artist(name=f"Loop {tag}", slug=f"loop-{tag}")
    b = Artist(name=f"Loop B {tag}", slug=f"loop-b-{tag}")
    s.add_all([a, b])
    await s.flush()
    a.merged_into_id = b.id
    b.merged_into_id = a.id  # corrupt: a merge cycle with no live survivor
    await s.commit()

    entry = await s.get(TracklistEntry, uuid.UUID(entry_ids[0]))
    track = await accept_candidate(
        s, entry, title="Round", artist_name=f"Loop {tag}", external_ids={},
        confirmed_via_acoustid=False, field_priority={}, providers=[],
    )
    live = await s.get(Artist, track.primary_artist_id)
    assert live.id not in (a.id, b.id)
    assert live.merged_into_id is None and live.name == f"Loop {tag}"
    assert live.slug == f"loop-{tag}-2"


async def test_enrichment_lookup_matches_alias_casefold(session_with_set):
    s, _ls_id, entry_ids = session_with_set
    tag = uuid.uuid4().hex[:6]
    known = Artist(name=f"Known {tag}", slug=f"known-{tag}", aliases=[f"Alt_Name% {tag}"])
    s.add(known)
    await s.commit()

    entry = await s.get(TracklistEntry, uuid.UUID(entry_ids[0]))
    track = await accept_candidate(
        s, entry, title="Aka", artist_name=f"ALT_NAME% {tag}", external_ids={},
        confirmed_via_acoustid=False, field_priority={}, providers=[],
    )
    assert track.primary_artist_id == known.id


async def test_unique_slug_suffixes_and_counts_tombstones(session):
    s = session
    base = f"slugbase-{uuid.uuid4().hex[:6]}"
    assert await unique_slug(s, Artist, base) == base
    live = Artist(name="x", slug=base)
    s.add(live)
    await s.flush()
    assert await unique_slug(s, Artist, base) == f"{base}-2"
    tomb = Artist(name="y", slug=f"{base}-2", merged_into_id=live.id)
    s.add(tomb)
    await s.flush()
    assert await unique_slug(s, Artist, base) == f"{base}-3"


async def test_unique_slug_fallback_item_gets_name_hash(session):
    s = session
    a = await unique_slug(s, Artist, slugify("Кино"), name="Кино")
    b = await unique_slug(s, Artist, slugify("坂本龍一"), name="坂本龍一")
    assert a != "item" and b != "item" and a != b
    assert a.startswith("item-") and len(a) == len("item-") + 6
    # a name that genuinely slugs to "item" is not hashed
    plain = await unique_slug(s, Artist, slugify("Item"), name="Item")
    assert re.fullmatch(r"item(-\d+)?", plain)


def test_slugify_folds_accents():
    assert slugify("Âme") == "ame"
    assert slugify("Röyksopp") == "royksopp"
    assert slugify("DJ Koze & Friends") == "dj-koze-friends"


def test_slugify_fallback_and_truncate():
    assert slugify("日本語", fallback="untitled") == "untitled"
    assert slugify("!!!", fallback="untitled") == "untitled"
    assert slugify("日本語") == "item"
    cut = slugify("a" * 59 + " b" * 20, max_len=60)
    assert len(cut) <= 60
    assert not cut.endswith("-")
    assert cut == "a" * 59
