from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest


def _spool_upload(
    spool_dir: Path, upload_id: str = "abc123", *, owner: str | None,
    filename: str = "set.flac", data: bytes = b"fake-audio-bytes", offset: int | None = None,
) -> Path:
    """Write an upload the way tusd's filestore leaves it: the bytes at
    ``<id>`` plus an ``<id>.info`` JSON sidecar (with the owner stamped into
    its MetaData by our pre-create hook)."""
    src = spool_dir / upload_id
    src.write_bytes(data)
    meta = {"filename": filename, "filetype": "audio/flac"}
    if owner is not None:
        meta["setvault_owner"] = owner
    (spool_dir / f"{upload_id}.info").write_text(json.dumps({
        "ID": upload_id, "Size": len(data),
        "Offset": len(data) if offset is None else offset,
        "SizeIsDeferred": False, "MetaData": meta,
        "Storage": {"Type": "filestore", "Path": str(src)},
    }))
    return src


async def _hook(client, event_type: str, upload: dict):
    cookie = client.cookies.get("session")
    return await client.post(
        "/api/uploads/tusd-hooks",
        json={
            "Type": event_type,
            "Event": {
                "Upload": upload,
                "HTTPRequest": {"Header": {"Cookie": [f"session={cookie}"]}},
            },
        },
    )


async def _post_finish(client, *, storage_path: str):
    return await _hook(client, "post-finish", {
        "ID": "abc123",
        "Storage": {"Path": storage_path, "Type": "filestore"},
        # Deliberately not what's in .info: the hook must trust tusd's file.
        "MetaData": {"filename": "body.flac", "filetype": "audio/flac"},
    })


async def test_pre_create_stamps_the_owner_over_client_metadata(
    authed_admin_client, seeded_admin,
):
    response = await _hook(authed_admin_client, "pre-create", {
        "MetaData": {
            "filename": "set.flac", "filetype": "audio/flac",
            "setvault_owner": str(uuid.uuid4()),  # client trying to claim another id
        },
    })

    assert response.status_code == 200
    meta = response.json()["ChangeFileInfo"]["MetaData"]
    assert meta["setvault_owner"] == str(seeded_admin.id)
    assert meta["filename"] == "set.flac"


@pytest.fixture
def spool(authed_admin_client, tmp_path, monkeypatch):
    """A tus spool dir under tmp_path, with queue + MIME sniffing stubbed.
    Returns the spool dir; ``spool.enqueued`` collects enqueue calls."""
    from setvault_web import tusd_hooks

    spool_dir = tmp_path / "cache" / "tus"
    spool_dir.mkdir(parents=True)
    monkeypatch.setattr(tusd_hooks, "upload_dir", lambda: spool_dir)
    monkeypatch.setattr(tusd_hooks, "sniff_mime", lambda p: "audio/flac")

    enqueued: list[tuple[str, dict]] = []

    class _Q:
        def enqueue(self, func, **kwargs):
            enqueued.append((func, kwargs))

    monkeypatch.setattr(tusd_hooks, "queue", lambda: _Q())
    return SpoolFixture(spool_dir, enqueued)


class SpoolFixture:
    def __init__(self, path: Path, enqueued: list) -> None:
        self.path = path
        self.enqueued = enqueued


@pytest.fixture
async def media_root(authed_admin_client, tmp_path):
    r = await authed_admin_client.post("/api/media-roots", json={
        "name": "primary", "host_path": str(tmp_path / "media"), "default_for_ingest": True,
        "naming_template": None, "max_bytes": None,
    })
    assert r.status_code == 201, r.text


async def test_post_finish_creates_live_set_and_enqueues_pipeline(
    authed_admin_client, seeded_admin, spool, media_root,
):
    src = _spool_upload(spool.path, owner=str(seeded_admin.id))

    response = await _post_finish(authed_admin_client, storage_path=str(src))

    assert response.status_code == 200, response.text
    assert response.json()["live_set_id"]
    assert spool.enqueued[0][0] == "setvault_core.jobs.pipeline.run_pipeline"
    # The spooled copy and tusd's .info sidecar are removed once placed.
    assert list(spool.path.iterdir()) == []


async def test_post_finish_rejects_storage_path_outside_spool(
    authed_admin_client, tmp_path, spool, media_root,
):
    """Any logged-in session can reach the hook endpoint, so a forged
    post-finish must not be able to import an arbitrary host file."""
    outside = tmp_path / "private.flac"
    outside.write_bytes(b"someone else's audio")
    traversal = spool.path / ".." / ".." / "private.flac"

    for raw in (str(outside), str(traversal), str(spool.path)):
        r = await _post_finish(authed_admin_client, storage_path=raw)
        assert r.status_code == 400, (raw, r.text)
    assert outside.exists()


async def test_post_finish_rejects_another_users_upload(
    authed_admin_client, spool, media_root,
):
    """A forged hook pointing at someone else's spooled upload (or one with no
    owner stamp, e.g. started before this check existed) is refused."""
    for owner in (str(uuid.uuid4()), None):
        src = _spool_upload(spool.path, owner=owner)
        r = await _post_finish(authed_admin_client, storage_path=str(src))
        assert r.status_code == 403, r.text
        assert src.exists()
    assert spool.enqueued == []


async def test_post_finish_rejects_incomplete_upload(
    authed_admin_client, seeded_admin, spool, media_root,
):
    src = _spool_upload(spool.path, owner=str(seeded_admin.id), offset=3)

    r = await _post_finish(authed_admin_client, storage_path=str(src))

    assert r.status_code == 409, r.text
    assert spool.enqueued == []


async def test_post_finish_rejects_bad_filename_with_400(
    authed_admin_client, seeded_admin, spool,
):
    src = _spool_upload(spool.path, owner=str(seeded_admin.id), filename="..")

    r = await _post_finish(authed_admin_client, storage_path=str(src))

    assert r.status_code == 400, r.text


async def test_hook_rejects_disabled_user(authed_admin_client, seeded_admin, spool):
    from datetime import UTC, datetime

    from setvault_core.db import session_factory
    from setvault_core.models.identity import User

    src = _spool_upload(spool.path, owner=str(seeded_admin.id))
    async with session_factory()() as s:
        row = await s.get(User, seeded_admin.id)
        row.disabled_at = datetime.now(UTC)
        await s.commit()

    r = await _post_finish(authed_admin_client, storage_path=str(src))

    assert r.status_code == 401, r.text
