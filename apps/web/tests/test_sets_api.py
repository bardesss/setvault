import uuid as _uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from setvault_core.db import session_factory
from setvault_core.models.catalog import (
    Artist,
    LiveSet,
    LiveSetArtist,
    LiveSetTag,
    MediaRoot,
    Tag,
    Venue,
)
from setvault_core.models.identity import User
from sqlalchemy import select


async def test_list_sets_returns_only_published(authed_admin_client, seeded_live_set):
    response = await authed_admin_client.get("/api/sets")
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["status"] == "published"


async def test_get_set_by_slug(authed_admin_client, seeded_live_set):
    slug = seeded_live_set["slug"]
    response = await authed_admin_client.get(f"/api/sets/{slug}")
    assert response.status_code == 200
    body = response.json()
    assert body["slug"] == slug
    assert body["audio_stream_url"].endswith(f"/api/sets/{slug}/stream")


async def test_edit_set_replaces_artists_and_tags(authed_admin_client, seeded_live_set):
    slug = seeded_live_set["slug"]
    artist = await authed_admin_client.post("/api/catalog/artists", json={"name": "Jeff Mills"})
    response = await authed_admin_client.patch(f"/api/sets/{slug}", json={
        "title": "Renamed",
        "artist_ids": [artist.json()["id"]],
        "tag_names": ["techno", "vinyl"],
    })
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Renamed"
    assert [a["name"] for a in body["artists"]] == ["Jeff Mills"]
    assert sorted(body["tags"]) == ["techno", "vinyl"]


async def test_soft_delete_hides_from_list(authed_admin_client, seeded_live_set):
    slug = seeded_live_set["slug"]
    await authed_admin_client.delete(f"/api/sets/{slug}")
    listed = await authed_admin_client.get("/api/sets")
    assert listed.json()["items"] == []


async def test_get_state_defaults_to_zero(authed_admin_client, seeded_live_set):
    slug = seeded_live_set["slug"]
    response = await authed_admin_client.get(f"/api/sets/{slug}/state")
    assert response.status_code == 200
    body = response.json()
    assert body["position_seconds"] == 0
    assert body["completed"] is False


async def test_put_state_persists(authed_admin_client, seeded_live_set):
    slug = seeded_live_set["slug"]
    put = await authed_admin_client.put(
        f"/api/sets/{slug}/state",
        json={"position_seconds": 42.5, "completed": False},
    )
    assert put.status_code == 204
    response = await authed_admin_client.get(f"/api/sets/{slug}/state")
    body = response.json()
    assert body["position_seconds"] == 42.5
    assert body["completed"] is False


async def test_put_state_updates_existing(authed_admin_client, seeded_live_set):
    slug = seeded_live_set["slug"]
    await authed_admin_client.put(
        f"/api/sets/{slug}/state",
        json={"position_seconds": 10.0, "completed": False},
    )
    await authed_admin_client.put(
        f"/api/sets/{slug}/state",
        json={"position_seconds": 90.0, "completed": True},
    )
    response = await authed_admin_client.get(f"/api/sets/{slug}/state")
    body = response.json()
    assert body["position_seconds"] == 90.0
    assert body["completed"] is True


# ---- Library list: filters, sort, paging, facets ----------------------------


@pytest.fixture
async def library(authed_admin_client, tmp_path):
    """Factory that inserts LiveSets directly (own MediaRoot, no seeded set)."""
    async with session_factory()() as s:
        admin = (await s.execute(
            select(User).where(User.email == "admin@example.test")
        )).scalar_one()
        mr = MediaRoot(name=f"lib-{_uuid.uuid4().hex[:6]}", host_path=str(tmp_path))
        s.add(mr)
        await s.commit()
        mr_id, admin_id = mr.id, admin.id

    async def make(title, *, date=None, tags=(), venue_kind=None, artist=None,
                   status="published", deleted=False, duration=None, age_days=0):
        async with session_factory()() as s:
            venue = None
            if venue_kind:
                venue = Venue(name=f"V {venue_kind}", slug=f"v-{_uuid.uuid4().hex[:6]}",
                              kind=venue_kind)
                s.add(venue)
                await s.flush()
            live = LiveSet(
                slug=f"s-{_uuid.uuid4().hex[:8]}", title=title, date=date,
                media_root_id=mr_id, audio_path="a.flac", status=status,
                source_type="upload", uploaded_by=admin_id,
                venue_id=venue.id if venue else None, duration_seconds=duration,
                deleted_at=datetime.now(UTC) if deleted else None,
            )
            s.add(live)
            await s.flush()
            for name in tags:
                slug = name.lower()
                tag = (await s.execute(select(Tag).where(Tag.slug == slug))).scalar_one_or_none()
                if tag is None:
                    tag = Tag(name=name, slug=slug)
                    s.add(tag)
                    await s.flush()
                s.add(LiveSetTag(live_set_id=live.id, tag_id=tag.id))
            if artist:
                a = (await s.execute(
                    select(Artist).where(Artist.name == artist)
                )).scalar_one_or_none()
                if a is None:
                    a = Artist(name=artist, slug=f"a-{_uuid.uuid4().hex[:6]}")
                    s.add(a)
                    await s.flush()
                s.add(LiveSetArtist(live_set_id=live.id, artist_id=a.id, position=0))
            await s.commit()
            if age_days:
                live.created_at = datetime.now(UTC) - timedelta(days=age_days)
                await s.commit()
            return live.slug

    return make


async def test_list_sets_paging(authed_admin_client, library):
    for i in range(3):
        await library(f"set {i}", date=date(2020, 1, i + 1))
    r = await authed_admin_client.get("/api/sets?limit=2")
    assert len(r.json()["items"]) == 2 and r.json()["total"] == 3
    r = await authed_admin_client.get("/api/sets?limit=2&offset=2")
    assert len(r.json()["items"]) == 1
    r = await authed_admin_client.get("/api/sets?offset=10")
    assert r.json()["items"] == [] and r.json()["total"] == 3


async def test_list_sets_filters(authed_admin_client, library):
    await library("Alpha night", date=date(2020, 5, 1), tags=["Techno"],
                  venue_kind="club", artist="Jeff Mills")
    await library("Beta day", date=date(2021, 5, 1), tags=["House"],
                  venue_kind="festival", artist="Ben Klock")
    await library("Gamma", date=date(2020, 6, 1), tags=["Techno"])

    async def total(qs):
        r = await authed_admin_client.get(f"/api/sets?{qs}")
        assert r.status_code == 200
        return r.json()["total"]

    assert await total("") == 3
    assert await total("tag=techno") == 2
    assert await total("year=2020") == 2
    assert await total("venue_kind=club") == 1
    assert await total("q=alpha") == 1
    assert await total("q=klock") == 1
    assert await total("tag=techno&year=2020&q=alpha") == 1
    assert await total("tag=house&year=2020") == 0


async def test_list_sets_sort_recent(authed_admin_client, library):
    await library("old but new", date=date(2010, 1, 1))
    await library("newer date", date=date(2022, 1, 1), age_days=5)
    r = await authed_admin_client.get("/api/sets?sort=recent")
    assert [i["title"] for i in r.json()["items"]] == ["old but new", "newer date"]
    r = await authed_admin_client.get("/api/sets?sort=date")
    assert [i["title"] for i in r.json()["items"]] == ["newer date", "old but new"]


async def test_list_sets_sort_title_and_duration(authed_admin_client, library):
    await library("B set", duration=100)
    await library("A set", duration=300)
    r = await authed_admin_client.get("/api/sets?sort=title")
    assert [i["title"] for i in r.json()["items"]] == ["A set", "B set"]
    r = await authed_admin_client.get("/api/sets?sort=duration")
    assert [i["title"] for i in r.json()["items"]] == ["A set", "B set"]


async def test_list_sets_limit_bounds(authed_admin_client):
    assert (await authed_admin_client.get("/api/sets?limit=0")).status_code == 422
    assert (await authed_admin_client.get("/api/sets?limit=201")).status_code == 422
    assert (await authed_admin_client.get("/api/sets?limit=200")).status_code == 200


async def test_list_sets_unknown_sort_422(authed_admin_client):
    assert (await authed_admin_client.get("/api/sets?sort=bogus")).status_code == 422


async def test_summary_has_venue_and_created_at(authed_admin_client, library):
    await library("with venue", venue_kind="club")
    await library("no venue")
    items = {i["title"]: i for i in (await authed_admin_client.get("/api/sets")).json()["items"]}
    assert items["with venue"]["venue"]["kind"] == "club"
    assert set(items["with venue"]["venue"]) == {"name", "slug", "kind"}
    assert items["no venue"]["venue"] is None
    assert items["no venue"]["created_at"]


async def test_facets(authed_admin_client, library):
    await library("a", date=date(2020, 1, 1), tags=["Techno"], venue_kind="club")
    await library("b", date=date(2021, 1, 1), tags=["Techno", "House"], venue_kind="club")
    await library("hidden draft", date=date(1999, 1, 1), tags=["Ghost"],
                  venue_kind="bar", status="draft")
    await library("hidden deleted", date=date(1998, 1, 1), tags=["Ghost"], deleted=True)
    r = await authed_admin_client.get("/api/sets/facets")
    assert r.status_code == 200
    body = r.json()
    assert body["years"] == [2021, 2020]
    assert body["venue_kinds"] == ["club"]
    assert body["tags"] == [
        {"slug": "techno", "name": "Techno", "count": 2},
        {"slug": "house", "name": "House", "count": 1},
    ]


async def _mk_artist(client, name):
    return (await client.post("/api/catalog/artists", json={"name": name})).json()["id"]


async def test_replace_artists_dedupes_and_keeps_roles(authed_admin_client, seeded_live_set):
    from setvault_core.models.catalog import LiveSetArtist

    slug = seeded_live_set["slug"]
    a = await _mk_artist(authed_admin_client, "Role A")
    b = await _mk_artist(authed_admin_client, "Role B")
    r = await authed_admin_client.patch(f"/api/sets/{slug}", json={"artist_ids": [a]})
    assert r.status_code == 200
    async with session_factory()() as s:
        row = (await s.execute(select(LiveSetArtist).where(
            LiveSetArtist.artist_id == _uuid.UUID(a)))).scalar_one()
        row.role = "guest"
        await s.commit()
    r = await authed_admin_client.patch(f"/api/sets/{slug}", json={"artist_ids": [b, a, b, a]})
    assert r.status_code == 200, r.text
    assert [x["name"] for x in r.json()["artists"]] == ["Role B", "Role A"]
    async with session_factory()() as s:
        rows = (await s.execute(select(LiveSetArtist).where(
            LiveSetArtist.live_set_id == _uuid.UUID(seeded_live_set["id"])))).scalars().all()
        roles = {str(x.artist_id): x.role for x in rows}
    assert roles[a] == "guest"
    assert roles[b] == "main"


async def test_replace_artists_rejects_merged_or_unknown(authed_admin_client, seeded_live_set):
    slug = seeded_live_set["slug"]
    a = await _mk_artist(authed_admin_client, "Survivor X")
    b = await _mk_artist(authed_admin_client, "Merged X")
    m = await authed_admin_client.post(
        f"/api/catalog/artists/{b}/merge", json={"survivor_id": a})
    assert m.status_code in (200, 204), m.text
    for bad in (b, "00000000-0000-0000-0000-000000000001"):
        r = await authed_admin_client.patch(f"/api/sets/{slug}", json={"artist_ids": [bad]})
        assert r.status_code in (404, 422), r.text


async def test_replace_tags_case_variants(authed_admin_client, seeded_live_set):
    slug = seeded_live_set["slug"]
    r = await authed_admin_client.patch(
        f"/api/sets/{slug}", json={"tag_names": ["House", "house", " HOUSE ", "  "]})
    assert r.status_code == 200, r.text
    assert len(r.json()["tags"]) == 1


async def test_tag_too_long_422(authed_admin_client, seeded_live_set):
    slug = seeded_live_set["slug"]
    r = await authed_admin_client.patch(f"/api/sets/{slug}", json={"tag_names": ["x" * 81]})
    assert r.status_code == 422
