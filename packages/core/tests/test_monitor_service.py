import uuid
from datetime import UTC, datetime, timedelta

import pytest
from setvault_core.models.identity import User
from setvault_core.services import monitors as svc
from setvault_core.services.passwords import hash_password


async def _make_user(session) -> uuid.UUID:
    user = User(
        email=f"u-{uuid.uuid4().hex[:6]}@x.test",
        username=f"u{uuid.uuid4().hex[:6]}",
        display_name="u",
        password_hash=hash_password("aaaaaaaa"),
    )
    session.add(user)
    await session.flush()
    return user.id


@pytest.mark.asyncio
async def test_create_query_monitor(session):
    uid = await _make_user(session)
    m = await svc.create_monitor(
        session, owner_user_id=uid, kind="query", query_text="Bicep",
        source_kind=None, external_id=None,
    )
    assert m.id is not None
    assert m.kind == "query"
    assert m.enabled is True
    assert m.per_poll_cap == 5


@pytest.mark.asyncio
async def test_create_query_monitor_requires_query_text(session):
    with pytest.raises(ValueError):
        await svc.create_monitor(
            session, owner_user_id=uuid.uuid4(), kind="query",
            query_text=None, source_kind=None, external_id=None,
        )


@pytest.mark.asyncio
async def test_create_entity_monitor_requires_source_and_external_id(session):
    with pytest.raises(ValueError):
        await svc.create_monitor(
            session, owner_user_id=uuid.uuid4(), kind="entity",
            query_text=None, source_kind="youtube", external_id=None,
        )


@pytest.mark.asyncio
async def test_due_monitors_respects_interval(session):
    uid = await _make_user(session)
    now = datetime.now(UTC)
    fresh = await svc.create_monitor(session, owner_user_id=uid, kind="query",
                                     query_text="a", source_kind=None, external_id=None)
    fresh.last_checked_at = now
    stale = await svc.create_monitor(session, owner_user_id=uid, kind="query",
                                     query_text="b", source_kind=None, external_id=None)
    stale.last_checked_at = now - timedelta(hours=2)
    never = await svc.create_monitor(session, owner_user_id=uid, kind="query",
                                     query_text="c", source_kind=None, external_id=None)
    never.last_checked_at = None
    await session.flush()

    due = await svc.due_monitors(session, interval_seconds=3600, now=now)
    due_ids = {m.id for m in due}
    assert stale.id in due_ids
    assert never.id in due_ids
    assert fresh.id not in due_ids


@pytest.mark.asyncio
async def test_due_monitors_skip_disabled_owner(session):
    now = datetime.now(UTC)
    active_uid = await _make_user(session)
    disabled_uid = await _make_user(session)
    disabled = await session.get(User, disabled_uid)
    disabled.disabled_at = now
    active_m = await svc.create_monitor(session, owner_user_id=active_uid, kind="query",
                                        query_text="a", source_kind=None, external_id=None)
    disabled_m = await svc.create_monitor(session, owner_user_id=disabled_uid, kind="query",
                                          query_text="b", source_kind=None, external_id=None)
    await session.flush()

    due_ids = {m.id for m in await svc.due_monitors(session, interval_seconds=3600, now=now)}
    assert active_m.id in due_ids
    assert disabled_m.id not in due_ids
