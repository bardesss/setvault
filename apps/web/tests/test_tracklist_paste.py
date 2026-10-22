from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "tracklists" / "sample_paste.txt"


@pytest.mark.asyncio
async def test_paste_returns_parsed_entries(authed_admin_client, seeded_live_set):
    slug = seeded_live_set["slug"]
    text = FIXTURE.read_text()
    r = await authed_admin_client.post(
        f"/api/sets/{slug}/tracklist/import",
        json={"kind": "paste", "payload": {"text": text}},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "succeeded"
    parsed = body["parsed"]
    assert len(parsed) == 3
    assert parsed[0]["start_seconds"] == 0
    assert parsed[0]["raw_label"] == "Aphex Twin - Xtal"
    assert parsed[1]["start_seconds"] == 225
    assert parsed[2]["raw_label"].startswith("Floating Points")


@pytest.mark.asyncio
async def test_paste_accept_materializes_entries(authed_admin_client, seeded_live_set):
    slug = seeded_live_set["slug"]
    imp = (await authed_admin_client.post(
        f"/api/sets/{slug}/tracklist/import",
        json={"kind": "paste", "payload": {"text": "0:00 A - B\n5:00 C - D"}},
    )).json()
    r = await authed_admin_client.post(
        f"/api/sets/{slug}/tracklist/import/{imp['id']}/accept",
        json={"accepted_indexes": [0, 1]},
    )
    assert r.status_code == 200
    listing = (await authed_admin_client.get(f"/api/sets/{slug}/tracklist")).json()
    assert len(listing["entries"]) == 2
    assert listing["entries"][0]["raw_label"] == "A - B"


async def _imp(client, slug, text="0:00 A - B\n5:00 C - D\n9:00 E - F"):
    return (await client.post(
        f"/api/sets/{slug}/tracklist/import",
        json={"kind": "paste", "payload": {"text": text}},
    )).json()


@pytest.mark.asyncio
async def test_accept_twice_409(authed_admin_client, seeded_live_set):
    slug = seeded_live_set["slug"]
    imp = await _imp(authed_admin_client, slug)
    url = f"/api/sets/{slug}/tracklist/import/{imp['id']}/accept"
    assert (await authed_admin_client.post(url, json={"accepted_indexes": [0]})).status_code == 200
    r = await authed_admin_client.post(url, json={"accepted_indexes": [0]})
    assert r.status_code == 409
    listing = (await authed_admin_client.get(f"/api/sets/{slug}/tracklist")).json()
    assert len(listing["entries"]) == 1


@pytest.mark.asyncio
async def test_accept_dedupes_indexes(authed_admin_client, seeded_live_set):
    slug = seeded_live_set["slug"]
    imp = await _imp(authed_admin_client, slug)
    r = await authed_admin_client.post(
        f"/api/sets/{slug}/tracklist/import/{imp['id']}/accept",
        json={"accepted_indexes": [0, 0, 1, 99, -1]},
    )
    assert r.status_code == 200
    assert len(r.json()["entries"]) == 2


@pytest.mark.asyncio
async def test_accept_appends_after_max_position(authed_admin_client, seeded_live_set):
    import uuid

    from setvault_core.db import session_factory
    from setvault_core.models.identity import User
    from setvault_core.models.tracklist import TracklistEntry
    from sqlalchemy import select

    slug = seeded_live_set["slug"]
    async with session_factory()() as s:
        admin = (await s.execute(
            select(User).where(User.email == "admin@example.test")
        )).scalar_one()
        s.add(TracklistEntry(
            live_set_id=uuid.UUID(seeded_live_set["id"]), position=5,
            start_seconds=1, raw_label="gap", created_by=admin.id,
        ))
        await s.commit()
    imp = await _imp(authed_admin_client, slug)
    r = await authed_admin_client.post(
        f"/api/sets/{slug}/tracklist/import/{imp['id']}/accept",
        json={"accepted_indexes": [0, 1]},
    )
    assert r.status_code == 200, r.text
    assert [e["position"] for e in r.json()["entries"]] == [5, 6, 7]
