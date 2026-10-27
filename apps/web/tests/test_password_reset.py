import pytest

pytestmark = pytest.mark.anyio


async def test_request_reset_unknown_email_returns_204_no_leak(client):
    response = await client.post("/api/password-reset/request",
                                 json={"email": "ghost@example.test"})
    assert response.status_code == 204


async def test_full_reset_cycle(client, seeded_admin, authed_admin_client):
    request = await authed_admin_client.post(
        "/api/password-reset/admin-link",
        json={"email": "admin@example.test"},
    )
    assert request.status_code == 200
    link = request.json()["reset_link"]
    token = link.rsplit("/", 1)[-1]
    redeem = await client.post(f"/api/password-reset/{token}/redeem",
                               json={"password": "new-strong-password-77"})
    assert redeem.status_code == 204

    login = await client.post("/api/auth/login",
                              json={"email": "admin@example.test",
                                    "password": "new-strong-password-77"})
    assert login.status_code == 200
