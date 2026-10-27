from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from setvault_core.models.catalog import LiveSet, MediaRoot
from setvault_core.models.identity import User
from setvault_core.models.playlists import PlayQueue
from setvault_core.services import play_queue as pq


async def _user(s) -> User:
    u = User(email=f"u{uuid.uuid4().hex[:6]}@x.test", username=f"u{uuid.uuid4().hex[:6]}",
             display_name="u", password_hash="x", role="member")
    s.add(u)
    await s.flush()
    return u


async def _sets(s, owner: User, specs: list[tuple[str, int | None]]) -> list[uuid.UUID]:
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

async def test_write_then_read_round_trip(session):
    u = await _user(session)
    a, b = await _sets(session, u, [("published", 60)] * 2)
    updated, _ = await pq.write_queue(session, u.id, [b, a], 1, None)
    sets, idx, ts = await pq.read_queue(session, u.id)
    assert [s.id for s in sets] == [b, a] and idx == 1 and ts == updated


async def test_read_without_row(session):
    u = await _user(session)
    assert await pq.read_queue(session, u.id) == ([], 0, None)


async def test_overwrote_newer_flag(session):
    u = await _user(session)
    a, = await _sets(session, u, [("published", 60)])
    first, flag = await pq.write_queue(session, u.id, [a], 0, None)
    assert flag is False
    _, flag = await pq.write_queue(session, u.id, [a], 0, first - timedelta(minutes=1))
    assert flag is True
    current = (await pq.read_queue(session, u.id))[2]
    _, flag = await pq.write_queue(session, u.id, [a], 0, current)
    assert flag is False
    _, flag = await pq.write_queue(session, u.id, [a], 0, None)
    assert flag is True


async def test_read_drops_invisible_and_keeps_current(session):
    u = await _user(session)
    a, b, c = await _sets(session, u, [("published", 1), ("draft", 1), ("published", 1)])
    await pq.write_queue(session, u.id, [a, b, c], 2, None)
    sets, idx, _ = await pq.read_queue(session, u.id)
    assert [s.id for s in sets] == [a, c] and idx == 1


async def test_read_clamps_index_when_current_dropped(session):
    u = await _user(session)
    a, b = await _sets(session, u, [("published", 1), ("published", 1)])
    await pq.write_queue(session, u.id, [a, b], 1, None)
    (await session.get(LiveSet, b)).deleted_at = datetime.now(UTC)
    await session.flush()
    sets, idx, _ = await pq.read_queue(session, u.id)
    assert [s.id for s in sets] == [a] and idx == 0


async def test_dedupes_on_write(session):
    u = await _user(session)
    a, b = await _sets(session, u, [("published", 1)] * 2)
    await pq.write_queue(session, u.id, [a, b, a], 0, None)
    sets, _, _ = await pq.read_queue(session, u.id)
    assert [s.id for s in sets] == [a, b]


async def test_cap_raises(session, monkeypatch):
    monkeypatch.setattr(pq, "MAX_QUEUE", 2)
    u = await _user(session)
    with pytest.raises(ValueError):
        await pq.write_queue(session, u.id, [uuid.uuid4() for _ in range(3)], 0, None)

async def test_naive_base_updated_at_is_treated_as_utc(session):
    u = await _user(session)
    a, = await _sets(session, u, [("published", 60)])
    stored, _ = await pq.write_queue(session, u.id, [a], 0, None)
    naive_old = (stored - timedelta(minutes=1)).replace(tzinfo=None)
    _, flag = await pq.write_queue(session, u.id, [a], 0, naive_old)
    assert flag is True
    current = (await pq.read_queue(session, u.id))[2]
    _, flag = await pq.write_queue(session, u.id, [a], 0, current.replace(tzinfo=None))
    assert flag is False


async def _repoint(session, ids, index, pick):
    """Queue of named ids -> (stored ids by name, index) after the merge."""
    u = await _user(session)
    loser, survivor, x = await _sets(session, u, [("published", 1)] * 3)
    names = {"loser": loser, "survivor": survivor, "x": x}
    inv = {v: k for k, v in names.items()}
    await pq.write_queue(session, u.id, [names[n] for n in ids], index, None)
    await pq.repoint_for_merge(session, loser_id=loser, survivor_id=survivor)
    row = await session.get(PlayQueue, u.id)
    await session.refresh(row)
    return [inv[i] for i in row.set_ids], row.current_index


async def test_merge_keeps_current_other_set(session):
    assert await _repoint(session, ["loser", "x", "survivor"], 1, None) == (["survivor", "x"], 1)


async def test_merge_current_loser_follows_earlier_survivor(session):
    assert await _repoint(session, ["survivor", "x", "loser"], 2, None) == (["survivor", "x"], 0)


async def test_merge_current_survivor_after_dedupe(session):
    assert await _repoint(session, ["loser", "survivor"], 1, None) == (["survivor"], 0)
