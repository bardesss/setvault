from setvault_core.db import init_engine, session_factory
from setvault_core.models.identity import User
from setvault_core.services.passwords import hash_password


async def test_admin_can_create_invite_and_link_is_returned(authed_admin_client):
    response = await authed_admin_client.post(
        "/api/invites",
        json={"email": "new@example.test", "role": "user"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "new@example.test"
    # Link now uses the configured BASE_URL (canonical origin), not the request host.
    assert body["invite_link"].startswith("http://localhost:1970/invite/")
    assert body["smtp_sent"] is False


async def test_redeem_invite_creates_user_and_logs_in(client, authed_admin_client):
    create = await authed_admin_client.post("/api/invites",
                                            json={"email": "new@example.test", "role": "user"})
    token = create.json()["invite_link"].rsplit("/", 1)[-1]
    redeem = await client.post(f"/api/invites/{token}/redeem", json={
        "username": "new", "display_name": "New User", "password": "correct horse",
    })
    assert redeem.status_code == 200
    assert redeem.json()["user"]["email"] == "new@example.test"
    assert "session" in redeem.cookies


async def test_redeem_invite_twice_fails(client, authed_admin_client):
    create = await authed_admin_client.post("/api/invites",
                                            json={"email": "x@x.test", "role": "user"})
    token = create.json()["invite_link"].rsplit("/", 1)[-1]
    first = await client.post(f"/api/invites/{token}/redeem", json={
        "username": "x", "display_name": "X", "password": "correct horse",
    })
    assert first.status_code == 200
    second = await client.post(f"/api/invites/{token}/redeem", json={
        "username": "y", "display_name": "Y", "password": "correct horse",
    })
    assert second.status_code in (400, 410)


async def test_redeem_rejects_short_password(client, authed_admin_client):
    create = await authed_admin_client.post("/api/invites",
                                            json={"email": "short@x.test", "role": "user"})
    token = create.json()["invite_link"].rsplit("/", 1)[-1]
    resp = await client.post(f"/api/invites/{token}/redeem", json={
        "username": "shorty", "display_name": "Shorty", "password": "a" * 11,
    })
    assert resp.status_code == 422


async def test_redeem_collision_with_two_users_is_400(client, authed_admin_client):
    import os

    init_engine(os.environ["TEST_DATABASE_URL"])
    async with session_factory()() as s:
        s.add(User(email="collide-a@x.test", username="collide_a", display_name="A",
                   password_hash=hash_password("correct horse"), role="user"))
        s.add(User(email="collide-b@x.test", username="collide_b", display_name="B",
                   password_hash=hash_password("correct horse"), role="user"))
        await s.commit()
    create = await authed_admin_client.post(
        "/api/invites", json={"email": "collide-a@x.test", "role": "user"})
    token = create.json()["invite_link"].rsplit("/", 1)[-1]
    resp = await client.post(f"/api/invites/{token}/redeem", json={
        "username": "collide_b", "display_name": "Both", "password": "correct horse",
    })
    assert resp.status_code == 400
