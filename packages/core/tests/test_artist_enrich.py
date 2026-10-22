import os
import uuid
from typing import ClassVar

import pytest
from setvault_core.db import init_engine, session_factory
from setvault_core.models.catalog import Artist
from setvault_core.services.artist_enrich import enrich_artist_entity
from setvault_providers.base import Capability, FieldValue, ProviderResult
from sqlalchemy import delete


class _FakeProvider:
    kind = "fake"
    capabilities: ClassVar[set[Capability]] = {Capability.ENRICH_ARTIST}

    async def enrich_artist(self, ref):
        return ProviderResult(kind="artist", raw_response={}, fields={
            "bio": FieldValue(value="from provider", confidence=0.9),
            "country": FieldValue(value="NL", confidence=0.8),
        })


@pytest.fixture(autouse=True)
def _engine():
    init_engine(os.environ["TEST_DATABASE_URL"])


@pytest.fixture(autouse=True)
async def _cleanup_artists():
    """Delete Artist rows before and after each test for idempotent reruns."""
    init_engine(os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql+asyncpg://setvault:setvault@localhost:5432/setvault",
    ))
    async with session_factory()() as s:
        await s.execute(delete(Artist))
        await s.commit()
    yield
    async with session_factory()() as s:
        await s.execute(delete(Artist))
        await s.commit()


async def test_enrich_writes_unlocked_fields_and_records_provenance(session):
    s = session
    a = Artist(name="Enrich Me", slug=f"e-{uuid.uuid4().hex[:6]}")
    s.add(a)
    await s.commit()

    written = await enrich_artist_entity(s, artist=a, providers=[_FakeProvider()])
    await s.commit()

    refreshed = await s.get(Artist, a.id)
    assert refreshed.bio == "from provider"
    assert refreshed.country == "NL"
    assert set(written) == {"bio", "country"}
    assert refreshed.enrichment_status["bio"]["set_by"] == "provider:fake"
    assert refreshed.enrichment_status["bio"]["locked"] is False


async def test_enrich_skips_locked_fields(session):
    s = session
    a = Artist(name="Locked", slug=f"l-{uuid.uuid4().hex[:6]}", bio="hand-written",
               enrichment_status={"bio": {"locked": True}})
    s.add(a)
    await s.commit()

    written = await enrich_artist_entity(s, artist=a, providers=[_FakeProvider()])
    await s.commit()

    refreshed = await s.get(Artist, a.id)
    assert refreshed.bio == "hand-written"  # locked field untouched
    assert "bio" not in written
    assert refreshed.country == "NL"  # unlocked field still written


async def test_enrich_noop_without_capable_provider(session):
    s = session
    a = Artist(name="NoProv", slug=f"n-{uuid.uuid4().hex[:6]}")
    s.add(a)
    await s.commit()
    written = await enrich_artist_entity(s, artist=a, providers=[])
    assert written == []


class _RichProvider:
    kind = "rich"
    capabilities: ClassVar[set[Capability]] = {Capability.ENRICH_ARTIST}

    async def enrich_artist(self, ref):
        return ProviderResult(kind="artist", raw_response={}, fields={
            "aliases": FieldValue(value=["AFX", "afx", "Polygon Window"], confidence=0.8),
            "socials": FieldValue(value={"bandcamp": "https://new", "youtube": "y"},
                                  confidence=0.8),
            "bio": FieldValue(value="provider bio", confidence=0.8),
        })


async def test_aliases_merged_casefold_deduped(session):
    s = session
    a = Artist(name="Al", slug=f"al-{uuid.uuid4().hex[:6]}", aliases=["Afx", "Old"])
    s.add(a)
    await s.commit()
    written = await enrich_artist_entity(s, artist=a, providers=[_RichProvider()])
    await s.commit()
    r = await s.get(Artist, a.id)
    assert r.aliases == ["Afx", "Old", "Polygon Window"]
    assert "aliases" in written


async def test_socials_merged_by_key(session):
    s = session
    a = Artist(name="So", slug=f"so-{uuid.uuid4().hex[:6]}",
               socials={"bandcamp": "https://old", "instagram": "i"})
    s.add(a)
    await s.commit()
    await enrich_artist_entity(s, artist=a, providers=[_RichProvider()])
    await s.commit()
    r = await s.get(Artist, a.id)
    assert r.socials == {"bandcamp": "https://new", "instagram": "i", "youtube": "y"}


async def test_locked_fields_untouched(session):
    s = session
    a = Artist(name="Lk", slug=f"lk-{uuid.uuid4().hex[:6]}", aliases=["Keep"],
               socials={"x": "1"},
               enrichment_status={"aliases": {"locked": True}, "socials": {"locked": True}})
    s.add(a)
    await s.commit()
    written = await enrich_artist_entity(s, artist=a, providers=[_RichProvider()])
    await s.commit()
    r = await s.get(Artist, a.id)
    assert r.aliases == ["Keep"] and r.socials == {"x": "1"}
    assert written == ["bio"]
