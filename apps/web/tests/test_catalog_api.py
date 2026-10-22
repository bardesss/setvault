async def test_create_and_get_artist(authed_admin_client):
    r = await authed_admin_client.post("/api/catalog/artists",
                                       json={"name": "Charlotte de Witte", "country": "BE"})
    assert r.status_code == 201
    slug = r.json()["slug"]
    assert slug == "charlotte-de-witte"
    show = await authed_admin_client.get(f"/api/catalog/artists/{slug}")
    assert show.status_code == 200 and show.json()["name"] == "Charlotte de Witte"


async def test_create_venue_with_kind(authed_admin_client):
    r = await authed_admin_client.post("/api/catalog/venues", json={
        "name": "De School", "kind": "club", "city_or_area": "Amsterdam", "country": "NL",
    })
    assert r.status_code == 201
    assert r.json()["kind"] == "club"


async def test_create_party_with_venue_and_series(authed_admin_client):
    series = await authed_admin_client.post("/api/catalog/series",
                                            json={"name": "Essential Mix"})
    venue = await authed_admin_client.post("/api/catalog/venues",
                                           json={"name": "BBC Radio 1", "kind": "studio"})
    r = await authed_admin_client.post("/api/catalog/parties", json={
        "name": "EM 2024-06-29", "venue_id": venue.json()["id"],
        "series_id": series.json()["id"], "date": "2024-06-29",
    })
    assert r.status_code == 201
    body = r.json()
    assert body["venue"]["name"] == "BBC Radio 1"
    assert body["series"]["name"] == "Essential Mix"


async def test_duplicate_name_gets_suffixed_slug(authed_admin_client):
    first = await authed_admin_client.post("/api/catalog/artists", json={"name": "Aphex Twin"})
    again = await authed_admin_client.post("/api/catalog/artists",
                                           json={"name": "Aphex Twin"})
    assert first.status_code == 201 and again.status_code == 201
    assert first.json()["slug"] == "aphex-twin"
    assert again.json()["slug"] == "aphex-twin-2"


async def test_create_artist_slug_collision_gets_suffix(authed_admin_client):
    a = await authed_admin_client.post("/api/catalog/artists", json={"name": "Café"})
    b = await authed_admin_client.post("/api/catalog/artists", json={"name": "Cafe"})
    assert a.status_code == 201 and b.status_code == 201
    assert a.json()["slug"] == "cafe"
    assert b.json()["slug"] == "cafe-2"


async def test_non_latin_name_slug_not_item_collision(authed_admin_client):
    slugs = []
    for name in ("Кино", "坂本龍一"):
        r = await authed_admin_client.post("/api/catalog/artists", json={"name": name})
        assert r.status_code == 201
        slugs.append(r.json()["slug"])
    assert slugs[0] != slugs[1]
    assert all(sl != "item" and sl.startswith("item-") for sl in slugs)
    for name, path in (("Кино", "venues"), ("Кино", "series"), ("Кино", "parties")):
        body = {"name": name, **({"kind": "club"} if path == "venues" else {})}
        r = await authed_admin_client.post(f"/api/catalog/{path}", json=body)
        assert r.status_code == 201
        assert r.json()["slug"].startswith("item-")


async def test_slug_suffix_counts_merged_tombstones(authed_admin_client):
    import os

    from setvault_core.db import init_engine, session_factory
    from setvault_core.models.catalog import Artist

    a = await authed_admin_client.post("/api/catalog/artists", json={"name": "Tomb Stone"})
    init_engine(os.environ["TEST_DATABASE_URL"])
    async with session_factory()() as s:
        keeper = Artist(name="Keeper", slug="keeper-tomb")
        s.add(keeper)
        await s.flush()
        row = await s.get(Artist, __import__("uuid").UUID(a.json()["id"]))
        row.merged_into_id = keeper.id
        await s.commit()
    b = await authed_admin_client.post("/api/catalog/artists", json={"name": "Tomb Stone"})
    assert b.status_code == 201
    assert b.json()["slug"] == "tomb-stone-2"
