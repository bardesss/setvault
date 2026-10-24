import os
import uuid

import pytest
from setvault_core.db import init_engine, session_factory
from setvault_core.models.catalog import Artist, LiveSet, LiveSetArtist, MediaRoot, Party, Venue


@pytest.fixture
async def artist_with_set(seeded_admin):
    init_engine(os.environ["TEST_DATABASE_URL"])
    async with session_factory()() as s:
        root = MediaRoot(name=f"r-{uuid.uuid4().hex[:6]}", host_path="/srv/test-media")
        s.add(root)
        await s.flush()
        artist = Artist(name="Mappable", slug=f"mappable-{uuid.uuid4().hex[:6]}")
        s.add(artist)
        await s.flush()
        ls = LiveSet(slug=f"s-{uuid.uuid4().hex[:8]}", title="A Live Set",
                     media_root_id=root.id, audio_path="a/b.flac", status="published",
                     source_type="upload", uploaded_by=seeded_admin.id)
        s.add(ls)
        await s.flush()
        s.add(LiveSetArtist(live_set_id=ls.id, artist_id=artist.id, position=0))
        await s.commit()
        yield {"slug": artist.slug, "set_title": "A Live Set"}


@pytest.mark.asyncio
async def test_sets_by_artist(authed_admin_client, artist_with_set):
    r = await authed_admin_client.get(f"/api/catalog/artists/{artist_with_set['slug']}/sets")
    assert r.status_code == 200
    titles = [i["title"] for i in r.json()["items"]]
    assert artist_with_set["set_title"] in titles


@pytest.mark.asyncio
async def test_sets_by_entity_unknown_slug_404(authed_admin_client):
    r = await authed_admin_client.get("/api/catalog/artists/no-such-artist/sets")
    assert r.status_code == 404


@pytest.fixture
async def an_artist(seeded_admin):
    init_engine(os.environ["TEST_DATABASE_URL"])
    async with session_factory()() as s:
        a = Artist(name="Edit Me", slug=f"edit-me-{uuid.uuid4().hex[:6]}", country="BE")
        s.add(a)
        await s.commit()
        yield a.slug


@pytest.mark.asyncio
async def test_member_can_edit_artist_fields_slug_unchanged(authed_admin_client, an_artist):
    r = await authed_admin_client.patch(
        f"/api/catalog/artists/{an_artist}", json={"country": "NL", "bio": "techno"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["country"] == "NL"
    assert body["bio"] == "techno"
    assert body["slug"] == an_artist  # slug is stable


@pytest.mark.asyncio
async def test_edit_requires_auth(client, an_artist):
    r = await client.patch(f"/api/catalog/artists/{an_artist}", json={"country": "NL"})
    assert r.status_code in (401, 403)  # CSRF middleware returns 403 before auth check


@pytest.mark.asyncio
async def test_edit_unknown_slug_404(authed_admin_client):
    r = await authed_admin_client.patch("/api/catalog/artists/nope", json={"country": "NL"})
    assert r.status_code == 404


@pytest.fixture
async def a_party_with_venue(seeded_admin):
    init_engine(os.environ["TEST_DATABASE_URL"])
    async with session_factory()() as s:
        venue = Venue(name="Club Alpha", slug=f"club-alpha-{uuid.uuid4().hex[:6]}", kind="club")
        s.add(venue)
        await s.flush()
        party = Party(name="Night Out", slug=f"night-out-{uuid.uuid4().hex[:6]}")
        s.add(party)
        await s.flush()
        await s.commit()
        yield {"party_slug": party.slug, "venue_id": str(venue.id), "venue_slug": venue.slug}


@pytest.mark.asyncio
async def test_member_can_edit_party_with_uuid_fields(authed_admin_client, a_party_with_venue):
    r = await authed_admin_client.patch(
        f"/api/catalog/parties/{a_party_with_venue['party_slug']}",
        json={"name": "Updated Night Out", "venue_id": a_party_with_venue["venue_id"]},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Updated Night Out"
    assert body["venue"] is not None
    assert body["venue"]["id"] == a_party_with_venue["venue_id"]


@pytest.mark.asyncio
async def test_edit_party_bad_uuid_422(authed_admin_client, a_party_with_venue):
    r = await authed_admin_client.patch(
        f"/api/catalog/parties/{a_party_with_venue['party_slug']}",
        json={"venue_id": "not-a-uuid"},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_edit_artist_null_aliases_ok(authed_admin_client, an_artist):
    # First, confirm initial state has aliases
    r_get = await authed_admin_client.get(f"/api/catalog/artists/{an_artist}")
    original_aliases = r_get.json()["aliases"]

    r = await authed_admin_client.patch(
        f"/api/catalog/artists/{an_artist}", json={"aliases": None}
    )
    assert r.status_code == 200  # must not 500
    body = r.json()
    assert body["aliases"] == original_aliases  # aliases unchanged — null treated as no-op


@pytest.mark.asyncio
async def test_party_patch_with_date_200(authed_admin_client, a_party_with_venue):
    from setvault_core.models.system import AuditEvent
    from sqlalchemy import select

    r = await authed_admin_client.patch(
        f"/api/catalog/parties/{a_party_with_venue['party_slug']}",
        json={"date": "2026-01-02"},
    )
    assert r.status_code == 200
    assert r.json()["date"] == "2026-01-02"
    async with session_factory()() as s:
        ev = (await s.execute(
            select(AuditEvent).where(AuditEvent.action == "party.edited")
        )).scalars().one()
    assert ev.after["date"] == "2026-01-02"


@pytest.mark.asyncio
async def test_artist_detail_includes_monitor_state(authed_admin_client, an_artist):
    r = await authed_admin_client.get(f"/api/catalog/artists/{an_artist}")
    assert r.status_code == 200, r.text
    assert r.json()["monitor"] is None
    artist_id = r.json()["id"]

    r = await authed_admin_client.post("/api/monitors", json={
        "kind": "query", "query_text": "Edit Me", "catalog_kind": "artist",
        "catalog_id": artist_id,
    })
    assert r.status_code == 201, r.text
    mid = r.json()["id"]
    r = await authed_admin_client.get(f"/api/catalog/artists/{an_artist}")
    assert r.json()["monitor"] == {"id": mid, "enabled": True}

    r = await authed_admin_client.delete(f"/api/monitors/{mid}")
    assert r.status_code == 204, r.text
    r = await authed_admin_client.get(f"/api/catalog/artists/{an_artist}")
    assert r.json()["monitor"] is None


@pytest.mark.asyncio
async def test_party_and_venue_detail_include_monitor_state(
    authed_admin_client, a_party_with_venue,
):
    for path, kind in (("parties", "party"), ("venues", "venue")):
        slug = a_party_with_venue[f"{kind}_slug"]
        r = await authed_admin_client.get(f"/api/catalog/{path}/{slug}")
        assert r.status_code == 200, r.text
        assert r.json()["monitor"] is None
        r = await authed_admin_client.post("/api/monitors", json={
            "kind": "query", "query_text": "x", "catalog_kind": kind,
            "catalog_id": r.json()["id"],
        })
        assert r.status_code == 201, r.text
        r = await authed_admin_client.get(f"/api/catalog/{path}/{slug}")
        assert r.json()["monitor"]["enabled"] is True


@pytest.mark.asyncio
async def test_entity_detail_monitor_null_when_user_cannot_monitor(client, an_artist):
    """A non-admin with monitoring switched off gets ``monitor: null`` even
    when a linked monitor of theirs exists (the gate, not the row, decides)."""
    from setvault_core.models.catalog import Artist
    from setvault_core.models.identity import User
    from setvault_core.models.monitors import Monitor
    from setvault_core.services.passwords import hash_password
    from sqlalchemy import select

    email, pw = f"u-{uuid.uuid4().hex[:6]}@x.test", "hunter2hunter2"
    async with session_factory()() as s:
        u = User(email=email, username=f"u{uuid.uuid4().hex[:6]}", display_name="u",
                 password_hash=hash_password(pw), role="user")
        s.add(u)
        await s.flush()
        artist = (await s.execute(select(Artist).where(Artist.slug == an_artist))).scalar_one()
        s.add(Monitor(owner_user_id=u.id, kind="query", query_text="Edit Me",
                      catalog_kind="artist", catalog_id=artist.id))
        await s.commit()

    login = await client.post("/api/auth/login", json={"email": email, "password": pw})
    assert login.status_code == 200, login.text
    client.cookies = login.cookies
    r = await client.get(f"/api/catalog/artists/{an_artist}")
    assert r.status_code == 200, r.text
    assert r.json()["monitor"] is None
