import os

import pytest


@pytest.fixture(autouse=True)
def _db():
    os.environ.setdefault(
        "TEST_DATABASE_URL", "postgresql+asyncpg://setvault:setvault@localhost:5432/setvault"
    )


async def test_login_with_seeded_user_returns_session_cookie(client, seeded_admin):
    response = await client.post(
        "/api/auth/login",
        json={"email": "admin@example.test", "password": "hunter2hunter2"},
    )
    assert response.status_code == 200
    assert "session" in response.cookies
    body = response.json()
    assert body["user"]["email"] == "admin@example.test"
    assert body["user"]["role"] == "admin"


async def test_login_wrong_password_returns_401(client, seeded_admin):
    response = await client.post(
        "/api/auth/login",
        json={"email": "admin@example.test", "password": "nope"},
    )
    assert response.status_code == 401


async def test_me_without_session_returns_401(client):
    response = await client.get("/api/auth/me")
    assert response.status_code == 401


async def test_logout_clears_cookie(client, seeded_admin):
    login = await client.post(
        "/api/auth/login",
        json={"email": "admin@example.test", "password": "hunter2hunter2"},
    )
    client.cookies = login.cookies
    csrf = login.cookies.get("csrf_token")
    response = await client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf})
    assert response.status_code == 204
    me = await client.get("/api/auth/me")
    assert me.status_code == 401


async def test_login_rehashes_outdated_hash(client, seeded_admin):
    from argon2 import PasswordHasher
    from setvault_core.db import session_factory
    from setvault_core.models.identity import User
    from setvault_core.services.passwords import needs_rehash, verify_password
    from sqlalchemy import select

    plain = "hunter2hunter2"
    weak = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1).hash(plain)
    assert needs_rehash(weak)
    async with session_factory()() as s:
        user = (await s.execute(
            select(User).where(User.email == "admin@example.test")
        )).scalar_one()
        user.password_hash = weak
        await s.commit()

    response = await client.post(
        "/api/auth/login", json={"email": "admin@example.test", "password": plain},
    )
    assert response.status_code == 200

    async with session_factory()() as s:
        stored = (await s.execute(
            select(User.password_hash).where(User.email == "admin@example.test")
        )).scalar_one()
    assert stored != weak
    assert not needs_rehash(stored)
    assert verify_password(plain, stored)
