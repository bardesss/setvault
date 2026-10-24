import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from setvault_core.db import session_factory
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
from sqlalchemy import select


@pytest.fixture
async def make_set(authed_admin_client, tmp_path):
    """Factory: insert a LiveSet linked to the given entities."""
    async with session_factory()() as s:
        admin = (await s.execute(
            select(User).where(User.email == "admin@example.test"))).scalar_one()
        mr = MediaRoot(name=f"br-{uuid.uuid4().hex[:6]}", host_path=str(tmp_path))
        s.add(mr)
        await s.commit()
        mr_id, admin_id = mr.id, admin.id

    async def make(*, artist_ids=(), venue_id=None, party_id=None, status="published",
                   deleted=False):
        async with session_factory()() as s:
            live = LiveSet(
                slug=f"s-{uuid.uuid4().hex[:8]}", title="t", media_root_id=mr_id,
                audio_path="a.flac", status=status, source_type="upload",
                uploaded_by=admin_id, venue_id=venue_id, party_id=party_id,
                deleted_at=datetime.now(UTC) if deleted else None,
            )
            s.add(live)
            await s.flush()
            for i, aid in enumerate(artist_ids):
                s.add(LiveSetArtist(live_set_id=live.id, artist_id=aid, position=i))
            await s.commit()
            return live.id

    return make


async def _artists(names, *, ages=None):
    """Insert artists; ``ages`` (days old) sets created_at. Returns name → id."""
    out = {}
    async with session_factory()() as s:
        for i, name in enumerate(names):
            a = Artist(name=name, slug=f"{name.lower().replace(' ', '-')}-{uuid.uuid4().hex[:4]}")
            if ages is not None:
                a.created_at = datetime.now(UTC) - timedelta(days=ages[i])
            s.add(a)
            await s.flush()
            out[name] = a.id
        await s.commit()
    return out


async def _list(client, kind, **params):
    r = await client.get(f"/api/catalog/{kind}", params=params)
    assert r.status_code == 200, r.text
    return r.json()


async def test_list_artists_paged_with_set_count(authed_admin_client, make_set):
    ids = await _artists(["Alpha", "Bravo", "Charlie"])
    await make_set(artist_ids=[ids["Alpha"]])
    await make_set(artist_ids=[ids["Alpha"]])
    await make_set(artist_ids=[ids["Bravo"]], status="draft")
    await make_set(artist_ids=[ids["Charlie"]], deleted=True)
    body = await _list(authed_admin_client, "artists")
    assert body["total"] == 3
    assert [(i["name"], i["set_count"]) for i in body["items"]] == [
        ("Alpha", 2), ("Bravo", 0), ("Charlie", 0)]
    assert set(body["items"][0]) == {"id", "name", "slug", "hint", "set_count"}
    assert body["items"][0]["id"] == str(ids["Alpha"])
    body = await _list(authed_admin_client, "artists", limit=2)
    assert len(body["items"]) == 2 and body["total"] == 3
    body = await _list(authed_admin_client, "artists", limit=2, offset=2)
    assert [i["name"] for i in body["items"]] == ["Charlie"] and body["total"] == 3


async def test_list_counts_for_venues_parties_series(authed_admin_client, make_set):
    async with session_factory()() as s:
        venue = Venue(name="Berghain", slug="berghain", kind="club", city_or_area="Berlin")
        series = Series(name="Klubnacht", slug="klubnacht")
        s.add_all([venue, series])
        await s.flush()
        party = Party(name="KN March", slug="kn-march", venue_id=venue.id,
                      series_id=series.id, date=date(2024, 3, 2))
        s.add(party)
        await s.commit()
        vid, pid = venue.id, party.id
    await make_set(venue_id=vid, party_id=pid)
    await make_set(venue_id=vid, party_id=pid)
    await make_set(venue_id=vid)
    venues = await _list(authed_admin_client, "venues")
    assert [(i["name"], i["hint"], i["set_count"]) for i in venues["items"]] == [
        ("Berghain", "Berlin", 3)]
    parties = await _list(authed_admin_client, "parties")
    assert [(i["name"], i["hint"], i["set_count"]) for i in parties["items"]] == [
        ("KN March", "2024-03-02 · Berghain", 2)]
    series_ = await _list(authed_admin_client, "series")
    assert [(i["name"], i["set_count"]) for i in series_["items"]] == [("Klubnacht", 2)]


async def test_list_sort_sets_and_recent(authed_admin_client, make_set):
    ids = await _artists(["Alpha", "Bravo", "Charlie"], ages=[1, 3, 2])
    await make_set(artist_ids=[ids["Charlie"]])
    await make_set(artist_ids=[ids["Charlie"]])
    await make_set(artist_ids=[ids["Bravo"]])
    body = await _list(authed_admin_client, "artists", sort="sets")
    assert [i["name"] for i in body["items"]] == ["Charlie", "Bravo", "Alpha"]
    body = await _list(authed_admin_client, "artists", sort="recent")
    assert [i["name"] for i in body["items"]] == ["Alpha", "Charlie", "Bravo"]
    r = await authed_admin_client.get("/api/catalog/artists", params={"sort": "plays"})
    assert r.status_code == 422


async def test_list_q_and_merged_excluded(authed_admin_client):
    keep = (await authed_admin_client.post(
        "/api/catalog/artists", json={"name": "Richie Hawtin", "aliases": ["Plastikman"]})).json()
    gone = (await authed_admin_client.post(
        "/api/catalog/artists", json={"name": "Richie H"})).json()
    await authed_admin_client.post("/api/catalog/artists", json={"name": "Ben Klock"})
    m = await authed_admin_client.post(
        f"/api/catalog/artists/{gone['id']}/merge", json={"survivor_id": keep["id"]})
    assert m.status_code == 200, m.text
    body = await _list(authed_admin_client, "artists", q="richie")
    assert [i["name"] for i in body["items"]] == ["Richie Hawtin"] and body["total"] == 1
    body = await _list(authed_admin_client, "artists", q="plastik")
    assert [i["name"] for i in body["items"]] == ["Richie Hawtin"]
    body = await _list(authed_admin_client, "artists")
    assert [i["name"] for i in body["items"]] == ["Ben Klock", "Richie Hawtin"]
    assert body["total"] == 2


async def test_list_empty_page(authed_admin_client):
    await _artists(["Alpha", "Bravo", "Charlie"])
    body = await _list(authed_admin_client, "artists", q="zzz")
    assert body == {"items": [], "total": 0}
    body = await _list(authed_admin_client, "artists", offset=999)
    assert body == {"items": [], "total": 3}


async def test_list_bad_kind_422(authed_admin_client):
    r = await authed_admin_client.get("/api/catalog/labels")
    assert r.status_code == 422
    r = await authed_admin_client.get("/api/catalog/tags")
    assert r.status_code == 422


async def test_list_limit_over_100_422(authed_admin_client):
    r = await authed_admin_client.get("/api/catalog/artists", params={"limit": 101})
    assert r.status_code == 422
    r = await authed_admin_client.get("/api/catalog/artists", params={"limit": 0})
    assert r.status_code == 422
    r = await authed_admin_client.get("/api/catalog/artists", params={"offset": -1})
    assert r.status_code == 422
    r = await authed_admin_client.get("/api/catalog/artists", params={"limit": 100})
    assert r.status_code == 200


async def test_list_requires_login(client):
    r = await client.get("/api/catalog/artists")
    assert r.status_code == 401


async def test_lookup_unchanged(authed_admin_client):
    """The shared query builder keeps lookup's prefix-first order and shape."""
    await authed_admin_client.post(
        "/api/catalog/artists", json={"name": "Richie Hawtin", "aliases": ["Plastikman"]})
    await authed_admin_client.post("/api/catalog/artists", json={"name": "The Plastic People"})
    r = await authed_admin_client.get(
        "/api/catalog/lookup", params={"kind": "artist", "q": "pla"})
    assert r.status_code == 200, r.text
    assert [i["name"] for i in r.json()] == ["Richie Hawtin", "The Plastic People"]
    assert set(r.json()[0]) == {"id", "name", "slug", "hint"}
