from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from setvault_core.models.catalog import LiveSet, MediaRoot
from setvault_core.models.identity import User
from setvault_core.models.playlists import Playlist, PlaylistItem
from setvault_core.services import playlists as svc
from sqlalchemy import select


async def _user(s) -> User:
    u = User(email=f"u{uuid.uuid4().hex[:6]}@x.test", username=f"u{uuid.uuid4().hex[:6]}",
             display_name="u", password_hash="x", role="member")
    s.add(u)
    await s.flush()
    return u


async def _sets(s, owner: User, specs: list[tuple[str, int | None]]) -> list[uuid.UUID]:
    """One set per (status, duration); returns their ids in order."""
    root = MediaRoot(name=f"r{uuid.uuid4().hex[:6]}", host_path="/srv/test-media", enabled=True)
    s.add(root)
    await s.flush()
    ids = []
    for status, dur in specs:
        ls = LiveSet(slug=f"s-{uuid.uuid4().hex[:8]}", title="t", media_root_id=root.id,
                     audio_path="x/y.flac", status=status, source_type="upload",
                     uploaded_by=owner.id, duration_seconds=dur)
        s.add(ls)
        await s.flush()
        ids.append(ls.id)
    return ids


async def _playlist(s, owner: User) -> Playlist:
    pl = Playlist(owner_user_id=owner.id, name="mine")
    s.add(pl)
    await s.flush()
    return pl


async def _rows(s, pl: Playlist) -> list[tuple[uuid.UUID, int]]:
    return [(r.live_set_id, r.position) for r in (await s.execute(
        select(PlaylistItem).where(PlaylistItem.playlist_id == pl.id)
        .order_by(PlaylistItem.position))).scalars()]


async def test_add_twice_is_noop(session):
    u = await _user(session)
    a, = await _sets(session, u, [("published", 60)])
    pl = await _playlist(session, u)
    assert await svc.add_item(session, pl, a) is True
    assert await svc.add_item(session, pl, a) is False
    assert await _rows(session, pl) == [(a, 0)]


async def test_remove_densifies_positions(session):
    u = await _user(session)
    a, b, c = await _sets(session, u, [("published", 60)] * 3)
    pl = await _playlist(session, u)
    for x in (a, b, c):
        await svc.add_item(session, pl, x)
    assert await svc.remove_item(session, pl, b) is True
    assert await svc.remove_item(session, pl, b) is False
    assert await _rows(session, pl) == [(a, 0), (c, 1)]


async def test_reorder_puts_hidden_items_last(session):
    u = await _user(session)
    a, hidden, c = await _sets(session, u, [("published", 60), ("draft", 60), ("published", 60)])
    pl = await _playlist(session, u)
    for x in (a, hidden, c):
        await svc.add_item(session, pl, x)
    await svc.reorder(session, pl, [c, a])
    assert await _rows(session, pl) == [(c, 0), (a, 1), (hidden, 2)]


async def test_reorder_rejects_mismatched_ids(session):
    u = await _user(session)
    a, b, extra = await _sets(session, u, [("published", 60)] * 3)
    pl = await _playlist(session, u)
    await svc.add_item(session, pl, a)
    await svc.add_item(session, pl, b)
    with pytest.raises(svc.PlaylistError):
        await svc.reorder(session, pl, [a])
    with pytest.raises(svc.PlaylistError):
        await svc.reorder(session, pl, [a, b, extra])
    assert await _rows(session, pl) == [(a, 0), (b, 1)]


async def test_list_counts_only_visible(session):
    u = await _user(session)
    a, gone, draft = await _sets(
        session, u, [("published", 60), ("published", 30), ("draft", 90)])
    pl = await _playlist(session, u)
    for x in (a, gone, draft):
        await svc.add_item(session, pl, x)
    (await session.get(LiveSet, gone)).deleted_at = datetime.now(UTC)
    await session.flush()
    assert await svc.list_owned(session, u.id) == [(pl, 1, 60)]


async def test_restored_set_reappears(session):
    u = await _user(session)
    a, b = await _sets(session, u, [("published", 60), ("published", 30)])
    pl = await _playlist(session, u)
    await svc.add_item(session, pl, a)
    await svc.add_item(session, pl, b)
    ls = await session.get(LiveSet, a)
    ls.deleted_at = datetime.now(UTC)
    await session.flush()
    assert [s.id for s, _ in await svc.visible_items(session, pl.id)] == [b]
    ls.deleted_at = None
    await session.flush()
    assert [(s.id, i.position) for s, i in await svc.visible_items(session, pl.id)] == [
        (a, 0), (b, 1)]


async def test_cap_raises(session, monkeypatch):
    monkeypatch.setattr(svc, "MAX_ITEMS", 2)
    u = await _user(session)
    a, b, c = await _sets(session, u, [("published", 60)] * 3)
    pl = await _playlist(session, u)
    await svc.add_item(session, pl, a)
    await svc.add_item(session, pl, b)
    with pytest.raises(svc.PlaylistError):
        await svc.add_item(session, pl, c)


async def test_get_owned_is_private_and_playlists_containing(session):
    u, other = await _user(session), await _user(session)
    a, = await _sets(session, u, [("published", 60)])
    pl = await _playlist(session, u)
    pl2 = Playlist(owner_user_id=u.id, name="aaa")
    session.add(pl2)
    await session.flush()
    await svc.add_item(session, pl, a)
    assert await svc.get_owned(session, other.id, pl.id) is None
    assert (await svc.get_owned(session, u.id, pl.id)).id == pl.id
    got = await svc.playlists_containing(session, u.id, a)
    assert [(p.name, c) for p, c in got] == [("aaa", False), ("mine", True)]