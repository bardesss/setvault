import uuid
from datetime import date

from setvault_core.db import session_factory
from setvault_core.models.catalog import Artist, LiveSet, LiveSetTag, MediaRoot, Party, Tag, Venue
from setvault_core.models.identity import User
from sqlalchemy import select


async def _lookup(client, kind, q="", **params):
    r = await client.get("/api/catalog/lookup", params={"kind": kind, "q": q, **params})
    assert r.status_code == 200, r.text
    return r.json()


async def test_lookup_artist_by_alias(authed_admin_client):
    await authed_admin_client.post(
        "/api/catalog/artists", json={"name": "Richie Hawtin", "aliases": ["Plastikman"]})
    await authed_admin_client.post("/api/catalog/artists", json={"name": "The Plastic People"})
    await authed_admin_client.post("/api/catalog/artists", json={"name": "Ben Klock"})
    rows = await _lookup(authed_admin_client, "artist", "plastik")
    assert [r["name"] for r in rows] == ["Richie Hawtin"]
    assert set(rows[0]) == {"id", "name", "slug", "hint"}
    assert rows[0]["hint"] is None
    # Prefix matches (name or alias) first, then the rest by name.
    rows = await _lookup(authed_admin_client, "artist", "pla")
    assert [r["name"] for r in rows] == ["Richie Hawtin", "The Plastic People"]
    rows = await _lookup(authed_admin_client, "artist", "the")
    assert [r["name"] for r in rows] == ["The Plastic People"]


async def test_lookup_excludes_merged(authed_admin_client):
    a = (await authed_admin_client.post(
        "/api/catalog/artists", json={"name": "Merge Keep"})).json()
    b = (await authed_admin_client.post(
        "/api/catalog/artists", json={"name": "Merge Gone"})).json()
    m = await authed_admin_client.post(
        f"/api/catalog/artists/{b['id']}/merge", json={"survivor_id": a["id"]})
    assert m.status_code == 200, m.text
    rows = await _lookup(authed_admin_client, "artist", "merge")
    assert [r["id"] for r in rows] == [a["id"]]


async def test_lookup_party_hint(authed_admin_client):
    venue = (await authed_admin_client.post(
        "/api/catalog/venues",
        json={"name": "Berghain", "kind": "club", "city_or_area": "Berlin"})).json()
    await authed_admin_client.post("/api/catalog/parties", json={
        "name": "Klubnacht A", "venue_id": venue["id"], "date": "2024-03-02"})
    await authed_admin_client.post("/api/catalog/parties", json={
        "name": "Klubnacht B", "date": "2024-03-09"})
    await authed_admin_client.post("/api/catalog/parties", json={
        "name": "Klubnacht C", "venue_id": venue["id"]})
    await authed_admin_client.post("/api/catalog/parties", json={"name": "Klubnacht D"})
    rows = await _lookup(authed_admin_client, "party", "klubnacht")
    assert [(r["name"], r["hint"]) for r in rows] == [
        ("Klubnacht A", "2024-03-02 · Berghain"),
        ("Klubnacht B", "2024-03-09"),
        ("Klubnacht C", "Berghain"),
        ("Klubnacht D", None),
    ]
    venues = await _lookup(authed_admin_client, "venue", "berg")
    assert [(r["name"], r["hint"]) for r in venues] == [("Berghain", "Berlin")]


async def test_lookup_tag_includes_unpublished_set_tags(authed_admin_client, tmp_path):
    async with session_factory()() as s:
        admin = (await s.execute(
            select(User).where(User.email == "admin@example.test"))).scalar_one()
        mr = MediaRoot(name=f"lk-{uuid.uuid4().hex[:6]}", host_path=str(tmp_path))
        s.add(mr)
        await s.flush()
        live = LiveSet(
            slug=f"draft-{uuid.uuid4().hex[:6]}", title="draft", media_root_id=mr.id,
            audio_path="a.flac", status="draft", source_type="upload", uploaded_by=admin.id,
        )
        tag = Tag(name="Dub Techno", slug="dub-techno")
        s.add_all([live, tag])
        await s.flush()
        s.add(LiveSetTag(live_set_id=live.id, tag_id=tag.id))
        await s.commit()
    rows = await _lookup(authed_admin_client, "tag", "dub")
    assert rows == [{"id": str(tag.id), "name": "Dub Techno", "slug": "dub-techno", "hint": None}]


async def test_lookup_limit_capped_25(authed_admin_client):
    async with session_factory()() as s:
        for i in range(30):
            s.add(Venue(name=f"Cap Venue {i:02d}", slug=f"cap-venue-{i:02d}", kind="club"))
        await s.commit()
    assert len(await _lookup(authed_admin_client, "venue", "cap")) == 10
    assert len(await _lookup(authed_admin_client, "venue", "cap", limit=100)) == 25
    assert len(await _lookup(authed_admin_client, "venue", "cap", limit=3)) == 3


async def test_lookup_bad_kind_422(authed_admin_client):
    r = await authed_admin_client.get("/api/catalog/lookup", params={"kind": "label", "q": "x"})
    assert r.status_code == 422
    r = await authed_admin_client.get("/api/catalog/lookup", params={"q": "x"})
    assert r.status_code == 422


async def test_lookup_requires_login(client):
    r = await client.get("/api/catalog/lookup", params={"kind": "artist", "q": "x"})
    assert r.status_code == 401


async def test_lookup_series_and_like_escape(authed_admin_client):
    async with session_factory()() as s:
        s.add(Artist(name="100% Pure", slug="100-pure"))
        s.add(Artist(name="1000 Hz", slug="1000-hz"))
        s.add(Party(name="unused", slug="unused-party", date=date(2020, 1, 1)))
        await s.commit()
    rows = await _lookup(authed_admin_client, "artist", "100%")
    assert [r["name"] for r in rows] == ["100% Pure"]
    await authed_admin_client.post("/api/catalog/series", json={"name": "Essential Mix"})
    rows = await _lookup(authed_admin_client, "series", "mix")
    assert [(r["name"], r["slug"], r["hint"]) for r in rows] == [
        ("Essential Mix", "essential-mix", None)]
