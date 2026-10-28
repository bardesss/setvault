async def test_me_returns_locale_null_by_default(authed_admin_client):
    response = await authed_admin_client.get("/api/auth/me")
    assert response.status_code == 200
    assert response.json()["locale"] is None


async def test_patch_locale_sets_value(authed_admin_client):
    response = await authed_admin_client.patch("/api/me", json={"locale": "nl"})
    assert response.status_code == 204
    me = await authed_admin_client.get("/api/auth/me")
    assert me.json()["locale"] == "nl"


async def test_patch_locale_null_clears(authed_admin_client):
    await authed_admin_client.patch("/api/me", json={"locale": "de"})
    response = await authed_admin_client.patch("/api/me", json={"locale": None})
    assert response.status_code == 204
    me = await authed_admin_client.get("/api/auth/me")
    assert me.json()["locale"] is None


async def test_patch_locale_rejects_unsupported(authed_admin_client):
    for bad in ("xx", "nl-NL", ""):
        response = await authed_admin_client.patch("/api/me", json={"locale": bad})
        assert response.status_code == 422, bad
    me = await authed_admin_client.get("/api/auth/me")
    assert me.json()["locale"] is None


async def test_patch_locale_requires_auth(client):
    response = await client.patch("/api/me", json={"locale": "nl"})
    assert response.status_code in (401, 403)


async def test_patch_locale_requires_csrf(client, seeded_admin):
    login = await client.post("/api/auth/login",
                              json={"email": "admin@example.test", "password": "hunter2hunter2"})
    client.cookies = login.cookies
    response = await client.patch("/api/me", json={"locale": "nl"})
    assert response.status_code == 403
