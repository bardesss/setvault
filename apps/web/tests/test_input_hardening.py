import pytest

BAD = "not-a-uuid"


@pytest.mark.asyncio
@pytest.mark.parametrize(("method", "path", "body"), [
    ("DELETE", "/api/sets/{slug}/bookmarks/" + BAD, None),
    ("POST", "/api/sets/{slug}/comments", {"body": "hi", "parent_id": BAD}),
    ("PATCH", "/api/comments/" + BAD, {"body": "x"}),
    ("DELETE", "/api/comments/" + BAD, None),
    ("POST", "/api/sets/{slug}/tracklist/entries/" + BAD + "/resolve", None),
    ("POST", "/api/sets/{slug}/tracklist/entries/" + BAD + "/resolve/accept", {}),
    ("POST", "/api/sets/{slug}/tracklist/entries/" + BAD + "/id-this", None),
    ("PUT", "/api/monitors/" + BAD, {"enabled": True}),
    ("DELETE", "/api/monitors/" + BAD, None),
    ("POST", "/api/me/discoveries/" + BAD + "/rip", None),
    ("POST", "/api/me/discoveries/" + BAD + "/dismiss", None),
    ("POST", "/api/me/notifications/" + BAD + "/read", None),
    ("PUT", "/api/me/notification-preferences/mention",
     {"channel": "in_app", "connector_id": BAD}),
    ("DELETE", "/api/me/rss-tokens/" + BAD, None),
    ("PATCH", "/api/sets/{slug}", {"party_id": BAD}),
    ("PATCH", "/api/sets/{slug}", {"venue_id": BAD}),
    ("PATCH", "/api/sets/{slug}", {"artist_ids": [BAD]}),
    ("POST", "/api/catalog/parties", {"name": "P", "venue_id": BAD}),
    ("POST", "/api/catalog/parties", {"name": "P", "series_id": BAD}),
    ("PATCH", "/api/sets/{slug}/tracklist/entries/" + BAD, {"raw_label": "x"}),
    ("DELETE", "/api/sets/{slug}/tracklist/entries/" + BAD, None),
    ("POST", "/api/sets/{slug}/tracklist/import/" + BAD + "/accept",
     {"accepted_indexes": [0]}),
])
async def test_bad_uuid_never_500(authed_admin_client, seeded_live_set, method, path, body):
    path = path.replace("{slug}", seeded_live_set["slug"])
    r = await authed_admin_client.request(method, path, json=body)
    assert r.status_code in (400, 404, 422), (r.status_code, r.text)


@pytest.mark.asyncio
async def test_unknown_referenced_ids_never_500(authed_admin_client, seeded_live_set):
    ghost = "00000000-0000-0000-0000-000000000001"
    slug = seeded_live_set["slug"]
    for body in ({"party_id": ghost}, {"venue_id": ghost}, {"artist_ids": [ghost]}):
        r = await authed_admin_client.patch(f"/api/sets/{slug}", json=body)
        assert r.status_code in (404, 422), (body, r.status_code, r.text)
    r = await authed_admin_client.post(
        "/api/catalog/parties", json={"name": "P", "venue_id": ghost})
    assert r.status_code in (404, 422), r.text


@pytest.mark.asyncio
async def test_party_patch_unknown_refs_422(authed_admin_client):
    ghost = "00000000-0000-0000-0000-000000000001"
    p = await authed_admin_client.post("/api/catalog/parties", json={"name": "PatchMe"})
    slug = p.json()["slug"]
    for body in ({"venue_id": ghost}, {"series_id": ghost}):
        r = await authed_admin_client.patch(f"/api/catalog/parties/{slug}", json=body)
        assert r.status_code == 422, r.text
