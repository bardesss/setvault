import uuid
from datetime import UTC, datetime

from setvault_core.db import session_factory
from setvault_core.models.catalog import LiveSet, MediaRoot
from setvault_core.models.identity import User
from setvault_core.models.system import AuditEvent
from sqlalchemy import select


async def test_admin_can_create_and_list_media_root(authed_admin_client, tmp_path):
    response = await authed_admin_client.post("/api/media-roots", json={
        "name": "primary", "host_path": str(tmp_path),
        "default_for_ingest": True, "naming_template": None, "max_bytes": None,
    })
    assert response.status_code == 201
    listed = await authed_admin_client.get("/api/media-roots")
    names = [r["name"] for r in listed.json()["items"]]
    assert "primary" in names


async def test_creating_root_at_nonexistent_path_warns_but_succeeds(authed_admin_client):
    response = await authed_admin_client.post("/api/media-roots", json={
        "name": "missing", "host_path": "/nonexistent/path/setvault",
        "default_for_ingest": False, "naming_template": None, "max_bytes": None,
    })
    assert response.status_code == 201
    body = response.json()
    assert body["last_health_status"] in ("unreachable", "unknown")


async def test_admin_can_delete_unused_media_root(authed_admin_client, tmp_path):
    created = await authed_admin_client.post("/api/media-roots", json={
        "name": "to-delete", "host_path": str(tmp_path),
        "default_for_ingest": False, "naming_template": None, "max_bytes": None,
    })
    rid = created.json()["id"]
    response = await authed_admin_client.delete(f"/api/media-roots/{rid}")
    assert response.status_code == 204
    listed = await authed_admin_client.get("/api/media-roots")
    assert rid not in [r["id"] for r in listed.json()["items"]]


async def test_delete_media_root_conflicts_when_liveset_references_it(
    authed_admin_client, tmp_path
):
    created = await authed_admin_client.post("/api/media-roots", json={
        "name": "with-set", "host_path": str(tmp_path),
        "default_for_ingest": False, "naming_template": None, "max_bytes": None,
    })
    rid = created.json()["id"]

    # Seed a LiveSet that points at this root
    async with session_factory()() as s:
        admin = (await s.execute(
            select(User).where(User.email == "admin@example.test")
        )).scalar_one()
        ls = LiveSet(
            media_root_id=uuid.UUID(rid),
            title="test set",
            slug=f"test-set-{uuid.uuid4().hex[:8]}",
            audio_path="audio.flac",
            uploaded_by=admin.id,
        )
        s.add(ls)
        await s.commit()
        ls_id = ls.id

    try:
        response = await authed_admin_client.delete(f"/api/media-roots/{rid}")
        assert response.status_code == 409
    finally:
        async with session_factory()() as s:
            row = await s.get(LiveSet, ls_id)
            if row is not None:
                await s.delete(row)
                await s.commit()


# --------------------------------------------------------------------------- #
# P2a A6: edit, probe, naming preview, set_count
# --------------------------------------------------------------------------- #

async def _make_root(c, tmp_path, name, **extra):
    body = {"name": name, "host_path": str(tmp_path), "default_for_ingest": False,
            "naming_template": None, "max_bytes": None, **extra}
    r = await c.post("/api/media-roots", json=body)
    assert r.status_code == 201, r.text
    return r.json()


async def _add_set(root_id, *, slug, deleted=False):
    async with session_factory()() as s:
        admin = (await s.execute(
            select(User).where(User.email == "admin@example.test")
        )).scalar_one()
        s.add(LiveSet(
            media_root_id=uuid.UUID(root_id), title=slug, slug=slug,
            audio_path="a.flac", uploaded_by=admin.id,
            deleted_at=datetime.now(UTC) if deleted else None,
        ))
        await s.commit()


async def _audit(action):
    async with session_factory()() as s:
        return (await s.execute(
            select(AuditEvent).where(AuditEvent.action == action)
        )).scalars().all()


async def test_patch_root_fields_and_audit(authed_admin_client, tmp_path):
    c = authed_admin_client
    root = await _make_root(c, tmp_path, "edit-me", max_bytes=100,
                            naming_template="{Slug}.{Ext}")
    r = await c.patch(f"/api/media-roots/{root['id']}", json={
        "name": "edited", "enabled": False, "max_bytes": None,
        "naming_template": "{Artist}/{Slug}.{Ext}",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "edited" and body["enabled"] is False
    assert body["max_bytes"] is None
    assert body["naming_template"] == "{Artist}/{Slug}.{Ext}"
    assert body["set_count"] == 0
    # untouched fields stay put
    again = (await c.get("/api/media-roots")).json()["items"]
    assert next(x for x in again if x["id"] == root["id"])["host_path"] == str(tmp_path)

    rows = await _audit("media_root.edited")
    assert len(rows) == 1
    assert rows[0].target_id == root["id"]
    assert rows[0].before == {
        "name": "edit-me", "enabled": True, "max_bytes": 100,
        "naming_template": "{Slug}.{Ext}",
    }
    assert rows[0].after == {
        "name": "edited", "enabled": False, "max_bytes": None,
        "naming_template": "{Artist}/{Slug}.{Ext}",
    }


async def test_patch_default_moves_flag(authed_admin_client, tmp_path):
    c = authed_admin_client
    a = await _make_root(c, tmp_path, "root-a", default_for_ingest=True)
    b = await _make_root(c, tmp_path, "root-b")
    r = await c.patch(f"/api/media-roots/{b['id']}", json={"default_for_ingest": True})
    assert r.status_code == 200
    assert r.json()["default_for_ingest"] is True
    items = {x["id"]: x for x in (await c.get("/api/media-roots")).json()["items"]}
    assert items[a["id"]]["default_for_ingest"] is False
    assert items[b["id"]]["default_for_ingest"] is True


async def test_disable_default_root_422(authed_admin_client, tmp_path):
    c = authed_admin_client
    a = await _make_root(c, tmp_path, "root-default", default_for_ingest=True)
    r = await c.patch(f"/api/media-roots/{a['id']}", json={"enabled": False})
    assert r.status_code == 422
    items = (await c.get("/api/media-roots")).json()["items"]
    assert next(x for x in items if x["id"] == a["id"])["enabled"] is True
    # dropping the default flag and disabling in one request is fine
    ok = await c.patch(f"/api/media-roots/{a['id']}",
                       json={"enabled": False, "default_for_ingest": False})
    assert ok.status_code == 200


async def test_patch_invalid_template_422(authed_admin_client, tmp_path):
    c = authed_admin_client
    root = await _make_root(c, tmp_path, "bad-template")
    r = await c.patch(f"/api/media-roots/{root['id']}",
                      json={"naming_template": "{Nope}/../x"})
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert isinstance(detail, list) and detail
    assert any("unknown token" in e for e in detail)
    # POST validates too
    post = await c.post("/api/media-roots", json={
        "name": "bad-post", "host_path": str(tmp_path), "naming_template": "{Slug}",
    })
    assert post.status_code == 422
    assert any("{Ext}" in e for e in post.json()["detail"])


async def test_probe_now_updates_health(authed_admin_client, tmp_path):
    c = authed_admin_client
    gone = tmp_path / "gone"
    gone.mkdir()
    root = await _make_root(c, gone, "probe-me")
    assert root["last_health_status"] == "ok"
    gone.rmdir()
    r = await c.post(f"/api/media-roots/{root['id']}/probe")
    assert r.status_code == 200
    assert r.json()["last_health_status"] == "unreachable"
    async with session_factory()() as s:
        row = await s.get(MediaRoot, uuid.UUID(root["id"]))
        assert row.last_health_status == "unreachable"
        assert row.last_health_check_at is not None


async def test_list_includes_set_count(authed_admin_client, tmp_path):
    c = authed_admin_client
    a = await _make_root(c, tmp_path, "count-a")
    b = await _make_root(c, tmp_path, "count-b")
    assert a["set_count"] == 0
    await _add_set(a["id"], slug=f"cnt-{uuid.uuid4().hex[:6]}")
    await _add_set(a["id"], slug=f"cnt-{uuid.uuid4().hex[:6]}")
    await _add_set(a["id"], slug=f"cnt-{uuid.uuid4().hex[:6]}", deleted=True)
    items = {x["id"]: x for x in (await c.get("/api/media-roots")).json()["items"]}
    assert items[a["id"]]["set_count"] == 2
    assert items[b["id"]]["set_count"] == 0
    p = await c.patch(f"/api/media-roots/{a['id']}", json={"name": "count-a2"})
    assert p.json()["set_count"] == 2


async def test_naming_preview_samples_and_errors(authed_admin_client, tmp_path):
    c = authed_admin_client
    # no sets: the built-in sample
    r = await c.post("/api/media-roots/naming-preview",
                     json={"template": "{Artist}/{Date}-{Slug}.{Ext}"})
    assert r.status_code == 200
    assert r.json() == {"errors": [], "warn_no_unique_token": False,
                        "samples": ["Example-Artist/2026-01-01-example-set.flac"]}

    # real sets: up to 3, never deleted ones
    root = await _make_root(c, tmp_path, "preview-root")
    for i in range(4):
        await _add_set(root["id"], slug=f"prev-{i}-{uuid.uuid4().hex[:4]}")
    await _add_set(root["id"], slug="prev-deleted", deleted=True)
    r2 = await c.post("/api/media-roots/naming-preview", json={"template": "{Slug}.{Ext}"})
    samples = r2.json()["samples"]
    assert len(samples) == 3
    assert all(s.startswith("prev-") and s.endswith(".flac") for s in samples)
    assert not any("deleted" in s for s in samples)

    bad = await c.post("/api/media-roots/naming-preview", json={"template": "{Nope}"})
    assert bad.status_code == 200
    assert any("unknown token" in e for e in bad.json()["errors"])
    assert bad.json()["samples"] == []
    # the built-in sample never reached the database
    async with session_factory()() as s:
        slugs = (await s.execute(select(LiveSet.slug))).scalars().all()
        assert "example-set" not in slugs


async def test_naming_preview_warns_without_unique_token(authed_admin_client):
    r = await authed_admin_client.post(
        "/api/media-roots/naming-preview", json={"template": "{Artist}/{Date}.{Ext}"},
    )
    body = r.json()
    assert body["errors"] == []
    assert body["warn_no_unique_token"] is True


async def test_bad_root_id_404(authed_admin_client):
    c = authed_admin_client
    assert (await c.patch("/api/media-roots/not-a-uuid", json={"name": "x"})).status_code == 404
    assert (await c.post("/api/media-roots/not-a-uuid/probe")).status_code == 404
    assert (await c.delete("/api/media-roots/not-a-uuid")).status_code == 404
    assert (await c.post("/api/media-roots/not-a-uuid/reapply-template")).status_code == 404
    missing = str(uuid.uuid4())
    assert (await c.patch(f"/api/media-roots/{missing}", json={"name": "x"})).status_code == 404
    assert (await c.post(f"/api/media-roots/{missing}/probe")).status_code == 404
