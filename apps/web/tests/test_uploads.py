from __future__ import annotations

import pytest


async def test_tusd_pre_create_hook_accepts_authenticated(authed_admin_client, tmp_path):
    create = await authed_admin_client.post("/api/media-roots", json={
        "name": "primary", "host_path": str(tmp_path), "default_for_ingest": True,
        "naming_template": None, "max_bytes": None,
    })
    assert create.status_code == 201
    cookie = authed_admin_client.cookies.get("session")
    response = await authed_admin_client.post(
        "/api/uploads/tusd-hooks",
        json={
            "Type": "pre-create",
            "Event": {
                "Upload": {
                    "MetaData": {"filename": "set.flac", "filetype": "audio/flac"},
                },
                "HTTPRequest": {"Header": {"Cookie": [f"session={cookie}"]}},
            },
        },
    )
    assert response.status_code == 200


async def test_post_finish_hook_creates_live_set_and_enqueues_pipeline(
    authed_admin_client, tmp_path, monkeypatch,
):
    enqueued: list[tuple[str, dict]] = []

    class _FakeJob:
        id = "test-job-id"

    class _FakeQueue:
        def enqueue(self, func, **kwargs):
            enqueued.append((func, kwargs))
            return _FakeJob()

    from setvault_web import tusd_hooks

    monkeypatch.setattr(tusd_hooks, "queue", lambda: _FakeQueue())
    monkeypatch.setattr(tusd_hooks, "sniff_mime", lambda p: "audio/flac")

    await authed_admin_client.post("/api/media-roots", json={
        "name": "primary", "host_path": str(tmp_path), "default_for_ingest": True,
        "naming_template": None, "max_bytes": None,
    })
    upload_dir = tmp_path / "tus"
    upload_dir.mkdir()
    monkeypatch.setattr(tusd_hooks, "upload_dir", lambda: upload_dir)
    src = upload_dir / "abc123"
    src.write_bytes(b"fake-audio-bytes")
    cookie = authed_admin_client.cookies.get("session")
    response = await authed_admin_client.post(
        "/api/uploads/tusd-hooks",
        json={
            "Type": "post-finish",
            "Event": {
                "Upload": {
                    "ID": "abc123",
                    "Size": len(b"fake-audio-bytes"),
                    "Storage": {"Path": str(src), "Type": "filestore"},
                    "MetaData": {"filename": "set.flac", "filetype": "audio/flac"},
                },
                "HTTPRequest": {"Header": {"Cookie": [f"session={cookie}"]}},
            },
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["live_set_id"]
    assert enqueued and enqueued[0][0] == "setvault_core.jobs.pipeline.run_pipeline"
    # The spooled copy (and tusd's .info sidecar) is removed once placed.
    assert not src.exists()


async def _post_finish(client, *, storage_path: str, filename: str = "set.flac"):
    cookie = client.cookies.get("session")
    return await client.post(
        "/api/uploads/tusd-hooks",
        json={
            "Type": "post-finish",
            "Event": {
                "Upload": {
                    "ID": "abc123",
                    "Storage": {"Path": storage_path, "Type": "filestore"},
                    "MetaData": {"filename": filename, "filetype": "audio/flac"},
                },
                "HTTPRequest": {"Header": {"Cookie": [f"session={cookie}"]}},
            },
        },
    )


@pytest.fixture
def spool(authed_admin_client, tmp_path, monkeypatch):
    """A tus spool dir under tmp_path, with queue + MIME sniffing stubbed."""
    from setvault_web import tusd_hooks

    spool_dir = tmp_path / "cache" / "tus"
    spool_dir.mkdir(parents=True)
    monkeypatch.setattr(tusd_hooks, "upload_dir", lambda: spool_dir)
    monkeypatch.setattr(tusd_hooks, "sniff_mime", lambda p: "audio/flac")

    class _Q:
        def enqueue(self, *_a, **_k):
            return None

    monkeypatch.setattr(tusd_hooks, "queue", lambda: _Q())
    return spool_dir


async def test_post_finish_rejects_storage_path_outside_spool(
    authed_admin_client, tmp_path, spool,
):
    """Any logged-in session can reach the hook endpoint, so a forged
    post-finish must not be able to import an arbitrary host file."""
    await authed_admin_client.post("/api/media-roots", json={
        "name": "primary", "host_path": str(tmp_path / "media"), "default_for_ingest": True,
        "naming_template": None, "max_bytes": None,
    })
    outside = tmp_path / "private.flac"
    outside.write_bytes(b"someone else's audio")
    traversal = spool / ".." / ".." / "private.flac"

    for raw in (str(outside), str(traversal), str(spool)):
        r = await _post_finish(authed_admin_client, storage_path=raw)
        assert r.status_code == 400, (raw, r.text)
    assert outside.exists()


async def test_post_finish_rejects_bad_filename_with_400(authed_admin_client, spool):
    src = spool / "abc123"
    src.write_bytes(b"x")

    r = await _post_finish(authed_admin_client, storage_path=str(src), filename="..")

    assert r.status_code == 400, r.text


async def test_hook_rejects_disabled_user(authed_admin_client, seeded_admin, spool):
    from datetime import UTC, datetime

    from setvault_core.db import session_factory
    from setvault_core.models.identity import User

    src = spool / "abc123"
    src.write_bytes(b"x")
    async with session_factory()() as s:
        row = await s.get(User, seeded_admin.id)
        row.disabled_at = datetime.now(UTC)
        await s.commit()

    r = await _post_finish(authed_admin_client, storage_path=str(src))

    assert r.status_code == 401, r.text
