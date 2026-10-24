import uuid

from setvault_core.db import session_factory
from setvault_core.models.catalog import Artist
from setvault_core.models.tracklist import Track


async def test_get_track(authed_admin_client):
    async with session_factory()() as s:
        artist = Artist(name="Derrick May", slug=f"derrick-may-{uuid.uuid4().hex[:4]}")
        s.add(artist)
        await s.flush()
        with_artist = Track(title="Strings of Life", primary_artist_id=artist.id)
        bare = Track(title="ID")
        s.add_all([with_artist, bare])
        await s.commit()
        with_id, bare_id = with_artist.id, bare.id
    r = await authed_admin_client.get(f"/api/tracks/{with_id}")
    assert r.status_code == 200, r.text
    assert r.json() == {
        "id": str(with_id), "title": "Strings of Life", "artist_name": "Derrick May"}
    r = await authed_admin_client.get(f"/api/tracks/{bare_id}")
    assert r.json() == {"id": str(bare_id), "title": "ID", "artist_name": None}


async def test_get_track_404(authed_admin_client):
    r = await authed_admin_client.get(f"/api/tracks/{uuid.uuid4()}")
    assert r.status_code == 404
    r = await authed_admin_client.get("/api/tracks/not-a-uuid")
    assert r.status_code == 404


async def test_get_track_requires_login(client):
    r = await client.get(f"/api/tracks/{uuid.uuid4()}")
    assert r.status_code == 401
