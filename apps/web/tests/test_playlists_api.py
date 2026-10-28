import uuid
from datetime import UTC, datetime

import pytest
from setvault_core.db import session_factory
from setvault_core.models.catalog import LiveSet
from setvault_core.models.identity import User
from setvault_core.services.passwords import hash_password
from sqlalchemy import select


async def _login(client, email: str) -> None:
    login = await client.post("/api/auth/login",
                              json={"email": email, "password": "hunter2hunter2"})
    assert login.status_code == 200, login.text
    client.cookies = login.cookies
    client.headers["X-CSRF-Token"] = login.cookies["csrf_token"]


async def _make_member(name: str = "pl-member") -> str:
    email = f"{name}@x.test"
    async with session_factory()() as s:
        s.add(User(email=email, username=name, display_name=name,
                   password_hash=hash_password("hunter2hunter2"), role="member"))
        await s.commit()
    return email


async def _more_sets(seeded_live_set, n: int) -> list[str]:
    """n extra published sets next to the seeded one (durations 100, 200, ...)."""
    slugs = []
    async with session_factory()() as s:
        src = (await s.execute(
            select(LiveSet).where(LiveSet.slug == seeded_live_set["slug"])
        )).scalar_one()
        for i in range(n):
            ls = LiveSet(
                slug=f"pl-{uuid.uuid4().hex[:8]}", title=f"extra {i}",
                media_root_id=src.media_root_id, audio_path=f"originals/seed/x{i}.flac",
                status="published", source_type="upload", uploaded_by=src.uploaded_by,
                duration_seconds=100 * (i + 1),
            )
            s.add(ls)
            slugs.append(ls.slug)
        await s.commit()
    return slugs


async def _set_state(slug: str, **fields) -> None:
    async with session_factory()() as s:
        ls = (await s.execute(select(LiveSet).where(LiveSet.slug == slug))).scalar_one()
        for k, v in fields.items():
            setattr(ls, k, v)
        await s.commit()


async def _create(client, name: str = "Mix") -> dict:
    r = await client.post("/api/me/playlists", json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()


async def _all_verbs_404(c, playlist_id: str, slug: str) -> None:
    base = f"/api/me/playlists/{playlist_id}"
    assert (await c.get(base)).status_code == 404
    assert (await c.patch(base, json={"name": "x"})).status_code == 404
    assert (await c.put(f"{base}/items", json={"slugs": []})).status_code == 404
    assert (await c.post(f"{base}/items", json={"slug": slug})).status_code == 404
    assert (await c.delete(f"{base}/items/{slug}")).status_code == 404
    assert (await c.delete(base)).status_code == 404


@pytest.mark.asyncio
async def test_create_list_get_round_trip(authed_admin_client):
    c = authed_admin_client
    made = await _create(c, "  Night drive  ")
    assert made["name"] == "Night drive"
    assert made["item_count"] == 0
    assert made["total_duration_seconds"] == 0
    assert made["items"] == []
    lst = (await c.get("/api/me/playlists")).json()
    assert [p["id"] for p in lst["items"]] == [made["id"]]
    got = (await c.get(f"/api/me/playlists/{made['id']}")).json()
    assert got["id"] == made["id"]
    assert got["description"] is None


@pytest.mark.asyncio
async def test_other_users_playlist_is_404(authed_admin_client, seeded_live_set):
    c = authed_admin_client
    slug = seeded_live_set["slug"]
    email = await _make_member()

    admin_pl = await _create(c, "admin's")
    await _login(c, email)
    member_pl = await _create(c, "member's")
    # the member against the admin's playlist
    await _all_verbs_404(c, admin_pl["id"], slug)
    assert [p["id"] for p in (await c.get("/api/me/playlists")).json()["items"]] == [
        member_pl["id"]]

    # admin (not the owner) against the member's playlist: admins get no override
    await _login(c, "admin@example.test")
    await _all_verbs_404(c, member_pl["id"], slug)
    # nothing above touched either playlist
    assert (await c.get(f"/api/me/playlists/{admin_pl['id']}")).status_code == 200
    await _login(c, email)
    assert (await c.get(f"/api/me/playlists/{member_pl['id']}")).status_code == 200


@pytest.mark.asyncio
async def test_bad_uuid_is_404(authed_admin_client, seeded_live_set):
    await _all_verbs_404(authed_admin_client, "not-a-uuid", seeded_live_set["slug"])


@pytest.mark.asyncio
async def test_add_duplicate_is_noop(authed_admin_client, seeded_live_set):
    c = authed_admin_client
    pl = await _create(c)
    url = f"/api/me/playlists/{pl['id']}/items"
    assert (await c.post(url, json={"slug": seeded_live_set["slug"]})).status_code == 204
    assert (await c.post(url, json={"slug": seeded_live_set["slug"]})).status_code == 204
    got = (await c.get(f"/api/me/playlists/{pl['id']}")).json()
    assert [i["slug"] for i in got["items"]] == [seeded_live_set["slug"]]
    assert got["item_count"] == 1


@pytest.mark.asyncio
async def test_add_hidden_set_is_404(authed_admin_client, seeded_live_set):
    c = authed_admin_client
    pl = await _create(c)
    url = f"/api/me/playlists/{pl['id']}/items"
    draft, deleted = await _more_sets(seeded_live_set, 2)
    await _set_state(draft, status="draft")
    await _set_state(deleted, deleted_at=datetime.now(UTC))
    assert (await c.post(url, json={"slug": draft})).status_code == 404
    assert (await c.post(url, json={"slug": deleted})).status_code == 404
    assert (await c.post(url, json={"slug": "no-such-" + uuid.uuid4().hex})
            ).status_code == 404
    assert (await c.get(f"/api/me/playlists/{pl['id']}")).json()["items"] == []


@pytest.mark.asyncio
async def test_reorder(authed_admin_client, seeded_live_set):
    c = authed_admin_client
    a = seeded_live_set["slug"]
    b, cc = await _more_sets(seeded_live_set, 2)
    pl = await _create(c)
    url = f"/api/me/playlists/{pl['id']}/items"
    for s in (a, b, cc):
        assert (await c.post(url, json={"slug": s})).status_code == 204
    r = await c.put(url, json={"slugs": [cc, a, b]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert [i["slug"] for i in body["items"]] == [cc, a, b]
    assert [i["position"] for i in body["items"]] == [0, 1, 2]
    again = (await c.get(f"/api/me/playlists/{pl['id']}")).json()
    assert [i["slug"] for i in again["items"]] == [cc, a, b]
    assert again["items"][0]["added_at"]


@pytest.mark.asyncio
async def test_reorder_with_wrong_set_of_slugs_is_400(authed_admin_client, seeded_live_set):
    c = authed_admin_client
    a = seeded_live_set["slug"]
    (b,) = await _more_sets(seeded_live_set, 1)
    pl = await _create(c)
    url = f"/api/me/playlists/{pl['id']}/items"
    for s in (a, b):
        await c.post(url, json={"slug": s})
    # stale list: one item missing
    assert (await c.put(url, json={"slugs": [a]})).status_code == 400
    # unknown slug
    assert (await c.put(url, json={"slugs": [a, "nope-" + uuid.uuid4().hex]})
            ).status_code == 400
    # duplicate slug
    assert (await c.put(url, json={"slugs": [a, a]})).status_code == 400
    got = (await c.get(f"/api/me/playlists/{pl['id']}")).json()
    assert [i["slug"] for i in got["items"]] == [a, b]


@pytest.mark.asyncio
async def test_hidden_set_not_listed_and_returns_after_restore(
    authed_admin_client, seeded_live_set,
):
    c = authed_admin_client
    a = seeded_live_set["slug"]
    (b,) = await _more_sets(seeded_live_set, 1)  # duration 100
    pl = await _create(c)
    url = f"/api/me/playlists/{pl['id']}/items"
    await c.post(url, json={"slug": a})
    await c.post(url, json={"slug": b})
    await _set_state(b, deleted_at=datetime.now(UTC))
    detail = (await c.get(f"/api/me/playlists/{pl['id']}")).json()
    assert [i["slug"] for i in detail["items"]] == [a]
    assert detail["item_count"] == 1
    assert detail["total_duration_seconds"] == 0  # the seeded set has no duration
    listed = (await c.get("/api/me/playlists")).json()["items"][0]
    assert listed["item_count"] == 1
    assert listed["total_duration_seconds"] == 0
    await _set_state(b, deleted_at=None)
    detail = (await c.get(f"/api/me/playlists/{pl['id']}")).json()
    assert [i["slug"] for i in detail["items"]] == [a, b]
    assert detail["item_count"] == 2
    assert detail["total_duration_seconds"] == 100


@pytest.mark.asyncio
async def test_remove_item(authed_admin_client, seeded_live_set):
    c = authed_admin_client
    a = seeded_live_set["slug"]
    b, other = await _more_sets(seeded_live_set, 2)
    pl = await _create(c)
    url = f"/api/me/playlists/{pl['id']}/items"
    await c.post(url, json={"slug": a})
    await c.post(url, json={"slug": b})
    assert (await c.delete(f"{url}/{a}")).status_code == 204
    got = (await c.get(f"/api/me/playlists/{pl['id']}")).json()
    assert [(i["slug"], i["position"]) for i in got["items"]] == [(b, 0)]
    # a known set that isn't in the playlist
    assert (await c.delete(f"{url}/{other}")).status_code == 204
    # an unknown slug
    assert (await c.delete(f"{url}/nope-{uuid.uuid4().hex}")).status_code == 404
    # the playlist itself
    assert (await c.delete(f"/api/me/playlists/{pl['id']}")).status_code == 204
    assert (await c.get(f"/api/me/playlists/{pl['id']}")).status_code == 404


@pytest.mark.asyncio
async def test_patch_rename_and_null_name_is_400(authed_admin_client):
    c = authed_admin_client
    pl = await _create(c, "Old")
    base = f"/api/me/playlists/{pl['id']}"
    r = await c.patch(base, json={"name": " New ", "description": "about"})
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "New"
    assert r.json()["description"] == "about"
    assert (await c.patch(base, json={"name": None})).status_code == 400
    assert (await c.patch(base, json={"name": "   "})).status_code == 400
    # the description can be cleared; omitted fields stay
    r = await c.patch(base, json={"description": None})
    assert r.status_code == 200
    assert r.json()["description"] is None
    assert r.json()["name"] == "New"


@pytest.mark.asyncio
async def test_name_too_long_is_400(authed_admin_client):
    c = authed_admin_client
    r = await c.post("/api/me/playlists", json={"name": "x" * 201})
    assert r.status_code in (400, 422)
    r = await c.post("/api/me/playlists", json={"name": "   "})
    assert r.status_code in (400, 422)
    pl = await _create(c)
    r = await c.patch(f"/api/me/playlists/{pl['id']}", json={"name": "x" * 201})
    assert r.status_code in (400, 422)


@pytest.mark.asyncio
async def test_set_playlists_flags_contains(authed_admin_client, seeded_live_set):
    c = authed_admin_client
    slug = seeded_live_set["slug"]
    one = await _create(c, "bravo")
    two = await _create(c, "Alpha")
    await c.post(f"/api/me/playlists/{one['id']}/items", json={"slug": slug})
    r = await c.get(f"/api/sets/{slug}/playlists")
    assert r.status_code == 200
    assert r.json()["items"] == [
        {"id": two["id"], "name": "Alpha", "contains": False},
        {"id": one["id"], "name": "bravo", "contains": True},
    ]
    assert (await c.get("/api/sets/nope-" + uuid.uuid4().hex + "/playlists")
            ).status_code == 404


@pytest.mark.asyncio
async def test_requires_login(client):
    fake = str(uuid.uuid4())
    assert (await client.get("/api/me/playlists")).status_code == 401
    assert (await client.get(f"/api/me/playlists/{fake}")).status_code == 401
    assert (await client.get("/api/sets/x/playlists")).status_code == 401


@pytest.mark.asyncio
async def test_add_past_cap_is_400(authed_admin_client, seeded_live_set, monkeypatch):
    from setvault_core.services import playlists as svc

    monkeypatch.setattr(svc, "MAX_ITEMS", 2)
    c = authed_admin_client
    a = seeded_live_set["slug"]
    b, d = await _more_sets(seeded_live_set, 2)
    pl = await _create(c)
    url = f"/api/me/playlists/{pl['id']}/items"
    assert (await c.post(url, json={"slug": a})).status_code == 204
    assert (await c.post(url, json={"slug": b})).status_code == 204
    assert (await c.post(url, json={"slug": d})).status_code == 400
    # a duplicate of a present set is still a no-op at the cap
    assert (await c.post(url, json={"slug": a})).status_code == 204
    # a reorder list longer than the cap is refused up front
    assert (await c.put(url, json={"slugs": [a, b, d]})).status_code == 400
    got = (await c.get(f"/api/me/playlists/{pl['id']}")).json()
    assert [i["slug"] for i in got["items"]] == [a, b]
