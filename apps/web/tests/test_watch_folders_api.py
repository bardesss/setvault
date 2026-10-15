from __future__ import annotations

import uuid

import pytest


@pytest.mark.asyncio
async def test_create_watch_folder_requires_admin(client, seeded_live_set, tmp_path):
    """Non-admin / no-session POST returns 401 or 403."""
    client.cookies.clear()
    r = await client.post("/api/admin/watch-folders", json={
        "name": "incoming",
        "host_path": str(tmp_path),
        "target_media_root_id": str(uuid.uuid4()),
    })
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_create_then_list_watch_folder(authed_admin_client, seeded_live_set, tmp_path):
    """Happy path: admin creates a watch folder, list returns it."""
    # seeded_live_set has already created a MediaRoot we can target
    mr_list = await authed_admin_client.get("/api/media-roots")
    assert mr_list.status_code == 200
    mr_id = mr_list.json()["items"][0]["id"]

    create = await authed_admin_client.post("/api/admin/watch-folders", json={
        "name": "incoming",
        "host_path": str(tmp_path),
        "target_media_root_id": mr_id,
    })
    assert create.status_code == 201, create.text
    wf = create.json()
    assert wf["name"] == "incoming"
    assert wf["host_path"] == str(tmp_path)
    assert wf["enabled"] is True

    # Ingests from this folder are attributed to the admin who created it.
    from setvault_core.db import session_factory
    from setvault_core.models.identity import User
    from setvault_core.models.watch_folder import WatchFolder
    async with session_factory()() as s:
        row = await s.get(WatchFolder, uuid.UUID(wf["id"]))
        creator = await s.get(User, row.created_by)
        assert creator.email == "admin@example.test"

    listing = await authed_admin_client.get("/api/admin/watch-folders")
    assert listing.status_code == 200
    items = listing.json()["items"]
    assert any(item["id"] == wf["id"] for item in items)


@pytest.mark.asyncio
async def test_patch_watch_folder_toggles_enabled(
    authed_admin_client, seeded_live_set, tmp_path,
):
    mr_list = await authed_admin_client.get("/api/media-roots")
    mr_id = mr_list.json()["items"][0]["id"]
    create = await authed_admin_client.post("/api/admin/watch-folders", json={
        "name": "wf", "host_path": str(tmp_path), "target_media_root_id": mr_id,
    })
    wf_id = create.json()["id"]

    patch = await authed_admin_client.patch(
        f"/api/admin/watch-folders/{wf_id}", json={"enabled": False},
    )
    assert patch.status_code == 200, patch.text
    assert patch.json()["enabled"] is False


@pytest.mark.asyncio
async def test_delete_watch_folder(authed_admin_client, seeded_live_set, tmp_path):
    mr_id = (await authed_admin_client.get("/api/media-roots")).json()["items"][0]["id"]
    create = await authed_admin_client.post("/api/admin/watch-folders", json={
        "name": "wf", "host_path": str(tmp_path), "target_media_root_id": mr_id,
    })
    wf_id = create.json()["id"]

    delete = await authed_admin_client.delete(f"/api/admin/watch-folders/{wf_id}")
    assert delete.status_code == 204

    listing = await authed_admin_client.get("/api/admin/watch-folders")
    assert all(item["id"] != wf_id for item in listing.json()["items"])


@pytest.mark.asyncio
async def test_list_unmatched_defaults_to_pending(
    authed_admin_client, seeded_live_set, tmp_path,
):
    """GET /api/admin/unmatched only shows pending rows unless ?resolution= overrides."""
    from setvault_core.db import session_factory
    from setvault_core.models.watch_folder import UnmatchedFile

    mr_id = (await authed_admin_client.get("/api/media-roots")).json()["items"][0]["id"]
    create = await authed_admin_client.post("/api/admin/watch-folders", json={
        "name": "wf", "host_path": str(tmp_path), "target_media_root_id": mr_id,
    })
    wf_id = uuid.UUID(create.json()["id"])

    async with session_factory()() as s:
        s.add(UnmatchedFile(
            watch_folder_id=wf_id,
            file_path="/srv/incoming/pending.opus",
            resolution="pending",
        ))
        s.add(UnmatchedFile(
            watch_folder_id=wf_id,
            file_path="/srv/incoming/discarded.opus",
            resolution="discarded",
        ))
        await s.commit()

    r = await authed_admin_client.get("/api/admin/unmatched")
    assert r.status_code == 200
    items = r.json()["items"]
    paths = {item["file_path"] for item in items}
    assert "/srv/incoming/pending.opus" in paths
    assert "/srv/incoming/discarded.opus" not in paths

    r2 = await authed_admin_client.get("/api/admin/unmatched?resolution=discarded")
    items2 = r2.json()["items"]
    paths2 = {item["file_path"] for item in items2}
    assert "/srv/incoming/discarded.opus" in paths2


@pytest.mark.asyncio
async def test_resolve_unmatched_link_to_set(
    authed_admin_client, seeded_live_set, tmp_path,
):
    """Linking an unmatched file to an existing set places the file under
    that set's originals/ and marks the row linked_to_set."""
    from setvault_core.db import session_factory
    from setvault_core.models.watch_folder import UnmatchedFile

    # Seed: create a watch folder + an unmatched file (with a real source file)
    mr_id = (await authed_admin_client.get("/api/media-roots")).json()["items"][0]["id"]
    create = await authed_admin_client.post("/api/admin/watch-folders", json={
        "name": "wf", "host_path": str(tmp_path), "target_media_root_id": mr_id,
    })
    wf_id = uuid.UUID(create.json()["id"])

    src = tmp_path / "drop" / "mystery.opus"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(b"\x00\x00\x00")

    async with session_factory()() as s:
        uf = UnmatchedFile(
            watch_folder_id=wf_id,
            file_path=str(src),
            resolution="pending",
        )
        s.add(uf)
        await s.commit()
        uf_id = uf.id

    resolve = await authed_admin_client.post(
        f"/api/admin/unmatched/{uf_id}/resolve",
        json={"action": "link_to_set", "live_set_id": seeded_live_set["id"]},
    )
    assert resolve.status_code == 200, resolve.text
    body = resolve.json()
    assert body["resolution"] == "linked_to_set"
    assert body["resolved_to_set_id"] == seeded_live_set["id"]


@pytest.mark.asyncio
async def test_resolve_unmatched_already_resolved_returns_409(
    authed_admin_client, seeded_live_set, tmp_path,
):
    from setvault_core.db import session_factory
    from setvault_core.models.watch_folder import UnmatchedFile

    mr_id = (await authed_admin_client.get("/api/media-roots")).json()["items"][0]["id"]
    create = await authed_admin_client.post("/api/admin/watch-folders", json={
        "name": "wf", "host_path": str(tmp_path), "target_media_root_id": mr_id,
    })
    wf_id = uuid.UUID(create.json()["id"])

    async with session_factory()() as s:
        uf = UnmatchedFile(
            watch_folder_id=wf_id,
            file_path="/srv/x.opus",
            resolution="discarded",
        )
        s.add(uf)
        await s.commit()
        uf_id = uf.id

    r = await authed_admin_client.post(
        f"/api/admin/unmatched/{uf_id}/resolve",
        json={"action": "discard"},
    )
    assert r.status_code == 409
