from __future__ import annotations


async def test_search_finds_set_by_title(authed_admin_client, seeded_live_set):
    response = await authed_admin_client.get("/api/search?q=seeded")
    assert response.status_code == 200
    body = response.json()
    titles = [r["title"] for r in body["sets"]]
    assert any("seeded" in t.lower() for t in titles)


async def test_search_finds_artist(authed_admin_client):
    await authed_admin_client.post("/api/catalog/artists", json={"name": "Helena Hauff"})
    response = await authed_admin_client.get("/api/search?q=hauff")
    assert response.status_code == 200
    assert any("Hauff" in a["name"] for a in response.json()["artists"])


async def test_search_hides_merged_entities(authed_admin_client):
    import os
    import uuid

    from setvault_core.db import init_engine, session_factory
    from setvault_core.models.catalog import Artist, Party, Series, Venue

    init_engine(os.environ["TEST_DATABASE_URL"])
    tag = uuid.uuid4().hex[:6]
    async with session_factory()() as s:
        for model, extra in ((Artist, {}), (Venue, {"kind": "club"}), (Party, {}), (Series, {})):
            live = model(name=f"Quuxly Live {tag}", slug=f"quuxly-live-{tag}", **extra)
            s.add(live)
            await s.flush()
            s.add(model(name=f"Quuxly Gone {tag}", slug=f"quuxly-gone-{tag}",
                        merged_into_id=live.id, **extra))
        await s.commit()

    r = await authed_admin_client.get("/api/search?q=quuxly")
    assert r.status_code == 200
    body = r.json()
    for key in ("artists", "parties", "venues", "series"):
        names = [e["name"] for e in body[key]]
        assert f"Quuxly Live {tag}" in names, key
        assert f"Quuxly Gone {tag}" not in names, key
