"""CLI: python -m setvault_web.reset_password (A6).

Every test creates its own throwaway admins (``*@example.test``, swept by the
autouse ``_cleanup_invite_users`` fixture) and never touches the seed admin.
"""

import uuid

import pytest
from setvault_core.db import session_factory
from setvault_core.models.identity import EmailToken, User
from setvault_core.models.system import AuditEvent
from setvault_core.services.passwords import hash_password, verify_password
from setvault_core.services.tokens import hash_token
from setvault_web.config import get_settings
from setvault_web.reset_password import pick_admin, reset_password
from sqlalchemy import select

NEW_PASSWORD = "a-brand-new-passphrase"


async def _make_admin() -> User:
    tag = uuid.uuid4().hex[:8]
    async with session_factory()() as s:
        user = User(
            email=f"locked-{tag}@example.test", username=f"locked-{tag}",
            display_name="Locked Out", password_hash=hash_password("old-password-123"),
            role="admin",
        )
        s.add(user)
        await s.commit()
        await s.refresh(user)
        return user


async def _reload(user_id) -> User:
    async with session_factory()() as s:
        return await s.get(User, user_id)


async def _audit_rows(user_id) -> list[AuditEvent]:
    async with session_factory()() as s:
        return list((await s.execute(
            select(AuditEvent).where(AuditEvent.action == "user.password_reset_cli",
                                     AuditEvent.target_id == str(user_id))
        )).scalars())


async def test_reset_sets_password_and_bumps_version():
    admin = await _make_admin()
    out = await reset_password(admin.email, new_password=NEW_PASSWORD, link=False)

    fresh = await _reload(admin.id)
    assert verify_password(NEW_PASSWORD, fresh.password_hash)
    assert fresh.session_version == admin.session_version + 1
    assert NEW_PASSWORD not in out
    assert admin.email in out
    assert len(await _audit_rows(admin.id)) == 1


async def test_link_mode_prints_reset_url():
    admin = await _make_admin()
    out = await reset_password(admin.email, new_password=None, link=True)

    prefix = f"{get_settings().base_url}/reset/"
    assert out.startswith(prefix)
    token = out[len(prefix):]
    async with session_factory()() as s:
        row = (await s.execute(
            select(EmailToken).where(EmailToken.token_hash == hash_token(token))
        )).scalar_one()
    assert row.kind == "password_reset"
    assert row.user_id == admin.id
    assert row.used_at is None

    fresh = await _reload(admin.id)
    assert verify_password("old-password-123", fresh.password_hash)  # unchanged
    assert fresh.session_version == admin.session_version + 1
    assert len(await _audit_rows(admin.id)) == 1


async def test_unknown_email_exits():
    with pytest.raises(SystemExit, match="no user"):
        await reset_password("nobody-here@example.test", new_password=NEW_PASSWORD, link=False)


async def test_short_password_exits():
    admin = await _make_admin()
    with pytest.raises(SystemExit, match="at least"):
        await reset_password(admin.email, new_password="short", link=False)
    fresh = await _reload(admin.id)
    assert verify_password("old-password-123", fresh.password_hash)
    assert fresh.session_version == admin.session_version
    assert await _audit_rows(admin.id) == []


async def test_multiple_admins_require_email():
    await _make_admin()
    await _make_admin()
    with pytest.raises(SystemExit, match="more than one admin; pass --email"):
        await reset_password(None, new_password=NEW_PASSWORD, link=False)


def test_pick_admin_defaults_to_the_sole_admin():
    sole = User(email="only@example.test", username="only", display_name="Only",
                password_hash="x", role="admin")
    assert pick_admin([sole]) is sole
    with pytest.raises(SystemExit, match="no admin"):
        pick_admin([])
