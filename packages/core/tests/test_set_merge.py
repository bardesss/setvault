"""Backfill library cleanup (Phase 7D Task 17): published sets that are the
same audio are merged into the older one; pairs the user protected go to the
Duplicates page instead."""
from __future__ import annotations

import array
import os
import random
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from setvault_core.db import init_engine, session_factory
from setvault_core.jobs import quality_backfill as qb
from setvault_core.models.base import Base
from setvault_core.models.catalog import (
    Artist,
    LiveSet,
    LiveSetArtist,
    LiveSetTag,
    MediaRoot,
    SetFingerprint,
    Tag,
)
from setvault_core.models.engagement import Favorite, ListeningHistory, UserSetState
from setvault_core.models.engagement_3c import (
    Bookmark,
    Comment,
    InAppNotification,
    PrivateNote,
)
from setvault_core.models.enrichment import ResolveJob
from setvault_core.models.identity import User
from setvault_core.models.tracklist import TracklistEntry, TracklistImportJob
from setvault_core.models.upgrades import SetUpgradeEvent
from setvault_core.models.url_rip import RipJob
from setvault_core.models.watch_folder import UnmatchedFile, WatchFolder
from setvault_core.services import set_merge, set_upgrade
from setvault_core.services.audio_match import ITEMS_PER_SECOND, raw_to_bytes
from setvault_core.services.system_config import get_config
from sqlalchemy import delete, func, select

TRIM = 100  # items the newer copy lacks at the start
OFFSET = TRIM / ITEMS_PER_SECOND  # ~12.4 s: the newer copy starts later


@pytest.fixture(autouse=True)
def _engine():
    init_engine(os.environ["TEST_DATABASE_URL"])


@pytest.fixture(autouse=True)
def webhooks(monkeypatch):
    calls: list = []

    async def fake(live, event):
        calls.append((live.id, event))

    monkeypatch.setattr(set_upgrade, "fan_out_webhooks", fake)
    return calls


@pytest.fixture
def fake_queue(monkeypatch):
    import rq

    calls: list = []

    class _Job:
        id = "job-next"

    def _enqueue(self, func, **kwargs):
        calls.append((func, kwargs))
        return _Job()

    monkeypatch.setattr(rq.Queue, "enqueue", _enqueue)
    return calls


def _items(seed: int, n: int = 2000) -> array.array:
    rng = random.Random(seed)  # noqa: S311
    return array.array("I", (rng.getrandbits(32) for _ in range(n)))


_QUALITY = {
    "lossless": dict(audio_codec="flac", audio_bitrate_kbps=900, audio_lossless=True),
    "ok": dict(audio_codec="mp3", audio_bitrate_kbps=128, audio_lossless=False),
}


class _Lib:
    def __init__(self, root: MediaRoot, owner: User):
        self.root, self.owner = root, owner
        self._t = datetime(2024, 1, 1, tzinfo=UTC)

    async def add(self, raw: array.array | None, *, tier: str = "ok", owner: User | None = None,
                  legacy_hash: str | None = None, **kw) -> uuid.UUID:
        """A published, processed set with a fingerprint; later calls are newer."""
        self._t += timedelta(days=1)
        sid = uuid.uuid4()
        async with session_factory()() as s:
            s.add(LiveSet(
                id=sid, slug=f"s-{sid.hex[:8]}", title=f"Set {sid.hex[:4]}",
                media_root_id=self.root.id, audio_path=f"originals/{sid}/a",
                streaming_path=f"stream/{sid}.opus", waveform_path=f"waveform/{sid}.json",
                duration_seconds=300, uploaded_by=(owner or self.owner).id,
                source_type="upload", status="published", created_at=self._t,
                quality_tier=tier, quality_measured_at=self._t, **_QUALITY[tier], **kw,
            ))
            await s.flush()
            n = len(raw) if raw is not None else 2000
            s.add(SetFingerprint(
                live_set_id=sid, fingerprint_hash=legacy_hash or uuid.uuid4().hex,
                duration_seconds=n / ITEMS_PER_SECOND,
                raw=raw_to_bytes(raw) if raw is not None else None,
                raw_version=1 if raw is not None else None,
            ))
            await s.commit()
        return sid


async def _user(role: str = "member") -> User:
    async with session_factory()() as s:
        u = User(email=f"u{uuid.uuid4().hex[:6]}@x.test", username=f"u{uuid.uuid4().hex[:6]}",
                 display_name="u", password_hash="x", role=role)
        s.add(u)
        await s.commit()
        return u


@pytest.fixture
async def lib(tmp_path):
    owner = await _user()
    async with session_factory()() as s:
        r = MediaRoot(name=f"r{uuid.uuid4().hex[:6]}", host_path=str(tmp_path), enabled=True)
        s.add(r)
        await s.commit()
    yield _Lib(r, owner)
    async with session_factory()() as s:
        await s.execute(delete(UnmatchedFile))
        await s.execute(delete(WatchFolder).where(WatchFolder.target_media_root_id == r.id))
        await s.execute(delete(RipJob).where(RipJob.live_set_id.is_(None)))
        await s.commit()


async def _get(sid: uuid.UUID) -> LiveSet:
    async with session_factory()() as s:
        return await s.get(LiveSet, sid)


async def _count(model, *where) -> int:
    async with session_factory()() as s:
        return (await s.execute(select(func.count()).select_from(model).where(*where))).scalar_one()


async def _cleanup() -> dict:
    """Run the cleanup phase to the end, as the job would."""
    totals = {"merged": 0, "skipped": 0, "errors": 0}
    cursor = None
    while True:
        res = await set_merge.run_cleanup_batch(cursor=cursor)
        for k in totals:
            totals[k] += res[k]
        if res["done"]:
            return totals
        cursor = res["cursor"]


# --------------------------------------------------------------------------


async def test_merge_moves_every_relation(lib):
    a = _items(1)
    older = await lib.add(a, tier="lossless")
    newer = await lib.add(a[TRIM:], tier="ok")
    other = await _user()  # has state on both sets
    held = uuid.uuid4()
    async with session_factory()() as s:
        u1, u2 = lib.owner.id, other.id
        art_shared = Artist(name="A", slug=f"a-{uuid.uuid4().hex[:6]}")
        art_new = Artist(name="B", slug=f"b-{uuid.uuid4().hex[:6]}")
        tag = Tag(name="t", slug=f"t-{uuid.uuid4().hex[:6]}")
        wf = WatchFolder(name="w", host_path=f"/watch/{uuid.uuid4().hex}",
                         target_media_root_id=lib.root.id)
        s.add_all([art_shared, art_new, tag, wf])
        await s.flush()
        now = datetime.now(UTC)
        s.add_all([
            LiveSetArtist(live_set_id=older, artist_id=art_shared.id, position=0),
            LiveSetArtist(live_set_id=newer, artist_id=art_shared.id, position=0),
            LiveSetArtist(live_set_id=newer, artist_id=art_new.id, position=1, role="b2b"),
            LiveSetTag(live_set_id=newer, tag_id=tag.id),
            Favorite(user_id=u1, live_set_id=newer),
            Favorite(user_id=u2, live_set_id=older),
            Favorite(user_id=u2, live_set_id=newer),
            UserSetState(user_id=u1, live_set_id=newer, position_seconds=100.0,
                         updated_at=now - timedelta(days=3)),
            # u2 played both; the newer set's state is more recent and wins.
            UserSetState(user_id=u2, live_set_id=older, position_seconds=5.0,
                         updated_at=now - timedelta(days=2)),
            UserSetState(user_id=u2, live_set_id=newer, position_seconds=200.0,
                         completed=True, updated_at=now - timedelta(days=1)),
            PrivateNote(user_id=u1, live_set_id=newer, body_md="note one"),
            PrivateNote(user_id=u2, live_set_id=older, body_md="older note"),
            PrivateNote(user_id=u2, live_set_id=newer, body_md="newer note"),
            ListeningHistory(user_id=u1, live_set_id=newer, last_position_seconds=50.0),
            Comment(live_set_id=newer, user_id=u1, position_seconds=120, body="drop!"),
            Comment(live_set_id=newer, user_id=u1, position_seconds=None, body="general"),
            Bookmark(live_set_id=newer, user_id=u1, position_seconds=300, label="b"),
            TracklistEntry(live_set_id=newer, position=0, start_seconds=60, end_seconds=90,
                           raw_label="t1", created_by=u1),
            TracklistImportJob(live_set_id=newer, kind="paste", payload={}, created_by=u1,
                               created_at=now),
            ResolveJob(live_set_id=newer, kind="bulk_resolve", payload={}, created_by=u1,
                       created_at=now),
            RipJob(live_set_id=newer, source_url="https://x.example/rip"),
            RipJob(live_set_id=None, upgrade_target_set_id=newer,
                   source_url="https://x.example/upgrade"),
            UnmatchedFile(watch_folder_id=wf.id, file_path="/watch/x.flac", audio_info={},
                          resolution="linked_to_set", resolved_to_set_id=newer),
            SetUpgradeEvent(live_set_id=newer, trigger="scheduled", outcome="rejected",
                            reason="not better", candidate_source_kind="youtube",
                            candidate_external_id="yt1"),
            InAppNotification(user_id=u1, kind="set_upgraded", subject_type="set",
                              subject_id=newer, payload={"set_slug": f"s-{newer.hex[:8]}"},
                              created_at=now),
        ])
        await s.flush()
        s.add(LiveSet(
            id=held, slug=f"h-{held.hex[:8]}", title="held", media_root_id=lib.root.id,
            audio_path="h", uploaded_by=u1, source_type="upload", status="draft",
            duplicate_of=newer, match_offset_seconds=3.0,
        ))
        await s.commit()

    async with session_factory()() as s:
        survivor = await s.get(LiveSet, older)
        loser = await s.get(LiveSet, newer)
        event = await set_merge.merge_pair(s, survivor=survivor, loser=loser,
                                           offset_seconds=OFFSET)
    assert event.outcome == "merged" and event.trigger == "backfill"

    shift = round(OFFSET)
    async with session_factory()() as s:
        # Nothing user-attached is left on the loser. Every table that
        # references live_sets is checked, so a relation added later fails
        # here until the merge handles it.
        import setvault_core.models  # noqa: F401  (every table in the metadata)

        own_rows = {"live_set_artists", "live_set_tags", "set_fingerprints"}
        checked = set()
        for table in Base.metadata.sorted_tables:
            for fk in table.foreign_keys:
                if fk.column.table.name != "live_sets" or table.name in own_rows:
                    continue
                col = fk.parent
                n = (await s.execute(
                    select(func.count()).select_from(table).where(col == newer)
                )).scalar_one()
                assert n == 0, f"{table.name}.{col.name} still references the loser"
                checked.add(f"{table.name}.{col.name}")
        assert {"comments.live_set_id", "rip_jobs.upgrade_target_set_id",
                "unmatched_files.resolved_to_set_id", "live_sets.duplicate_of",
                "set_upgrade_events.live_set_id"} <= checked
        # A new table referencing live_sets changes this count: teach
        # set_merge._merge_rows about it, seed it above, then update this.
        assert len(checked) == 14, sorted(checked)

        # Metadata: added to the survivor; the loser keeps its own.
        artists = (await s.execute(
            select(LiveSetArtist.artist_id, LiveSetArtist.position, LiveSetArtist.role)
            .where(LiveSetArtist.live_set_id == older).order_by(LiveSetArtist.position)
        )).all()
        assert [(r[0], r[1], r[2]) for r in artists] == [
            (art_shared.id, 0, "main"), (art_new.id, 1, "b2b")]
        assert await _count(LiveSetTag, LiveSetTag.live_set_id == older) == 1
        assert await _count(LiveSetArtist, LiveSetArtist.live_set_id == newer) == 2
        # Fingerprint stays with the loser's audio.
        assert await _count(SetFingerprint, SetFingerprint.live_set_id == newer) == 1

        favs = (await s.execute(
            select(Favorite.user_id).where(Favorite.live_set_id == older)
        )).scalars().all()
        assert set(favs) == {u1, u2}

        st1 = (await s.execute(select(UserSetState).where(
            UserSetState.user_id == u1, UserSetState.live_set_id == older))).scalar_one()
        assert st1.position_seconds == pytest.approx(100.0 + OFFSET)
        st2 = (await s.execute(select(UserSetState).where(
            UserSetState.user_id == u2, UserSetState.live_set_id == older))).scalar_one()
        assert st2.position_seconds == pytest.approx(200.0 + OFFSET) and st2.completed

        notes = dict((await s.execute(
            select(PrivateNote.user_id, PrivateNote.body_md)
            .where(PrivateNote.live_set_id == older))).all())
        assert notes[u1] == "note one"
        assert notes[u2] == "older note\n\nnewer note"

        hist = (await s.execute(select(ListeningHistory).where(
            ListeningHistory.live_set_id == older))).scalar_one()
        assert hist.last_position_seconds == pytest.approx(50.0 + OFFSET)
        comments = dict((await s.execute(select(Comment.body, Comment.position_seconds)
                                         .where(Comment.live_set_id == older))).all())
        assert comments == {"drop!": 120 + shift, "general": None}
        bm = (await s.execute(select(Bookmark).where(Bookmark.live_set_id == older))).scalar_one()
        assert bm.position_seconds == 300 + shift
        entry = (await s.execute(select(TracklistEntry).where(
            TracklistEntry.live_set_id == older))).scalar_one()
        assert (entry.start_seconds, entry.end_seconds) == (60 + shift, 90 + shift)
        assert await _count(TracklistImportJob, TracklistImportJob.live_set_id == older) == 1
        assert await _count(ResolveJob, ResolveJob.live_set_id == older) == 1
        assert await _count(RipJob, RipJob.live_set_id == older) == 1
        assert await _count(RipJob, RipJob.upgrade_target_set_id == older) == 1
        assert await _count(UnmatchedFile, UnmatchedFile.resolved_to_set_id == older) == 1
        h = await s.get(LiveSet, held)
        assert h.duplicate_of == older
        assert h.match_offset_seconds == pytest.approx(3.0 + OFFSET)
        notif = (await s.execute(select(InAppNotification).where(
            InAppNotification.user_id == u1))).scalar_one()
        assert notif.subject_id == older
        assert notif.payload["set_slug"] == f"s-{older.hex[:8]}"
        kinds = (await s.execute(select(SetUpgradeEvent.outcome).where(
            SetUpgradeEvent.live_set_id == older))).scalars().all()
        assert sorted(kinds) == ["merged", "rejected"]

        # The loser is in the recycle bin as a duplicate of the survivor.
        lo = await s.get(LiveSet, newer)
        assert lo.deleted_at is not None
        assert lo.purge_after_at - lo.deleted_at == timedelta(days=14)
        assert lo.status == "draft" and lo.duplicate_of == older
        assert lo.title.endswith("(merged copy)")
        su = await s.get(LiveSet, older)
        assert su.deleted_at is None and su.status == "published"
        assert su.quality_tier == "lossless"  # survivor's audio untouched


async def test_survivor_tracklist_is_kept_and_history_says_so(lib):
    a = _items(2)
    older = await lib.add(a, tier="lossless")
    newer = await lib.add(a[TRIM:], tier="ok")
    async with session_factory()() as s:
        for sid, label in ((older, "mine"), (newer, "theirs")):
            s.add(TracklistEntry(live_set_id=sid, position=0, start_seconds=0,
                                 raw_label=label, created_by=lib.owner.id))
        await s.commit()
        survivor, loser = await s.get(LiveSet, older), await s.get(LiveSet, newer)
        event = await set_merge.merge_pair(s, survivor=survivor, loser=loser,
                                           offset_seconds=OFFSET)
    assert event.reason == set_merge.TRACKLIST_KEPT
    assert await _count(TracklistEntry, TracklistEntry.live_set_id == older) == 1
    assert await _count(TracklistEntry, TracklistEntry.live_set_id == newer) == 1


async def test_equal_tiers_older_survives(lib):
    a = _items(3)
    older = await lib.add(a, tier="ok")
    newer = await lib.add(a[TRIM:], tier="ok")
    async with session_factory()() as s:
        s.add(Comment(live_set_id=newer, user_id=lib.owner.id, position_seconds=10, body="x"))
        await s.commit()

    assert await _cleanup() == {"merged": 1, "skipped": 0, "errors": 0}

    o, n = await _get(older), await _get(newer)
    assert o.deleted_at is None and n.deleted_at is not None
    assert o.audio_path == f"originals/{older}/a"  # no swap
    assert await _count(Comment, Comment.live_set_id == older) == 1


async def test_better_newer_copy_upgrades_older_then_merges(lib, webhooks):
    a = _items(4)
    older = await lib.add(a, tier="ok")
    newer = await lib.add(a[TRIM:], tier="lossless")
    async with session_factory()() as s:
        s.add_all([
            Comment(live_set_id=older, user_id=lib.owner.id, position_seconds=100, body="old"),
            Comment(live_set_id=newer, user_id=lib.owner.id, position_seconds=100, body="new"),
        ])
        await s.commit()

    assert await _cleanup() == {"merged": 1, "skipped": 0, "errors": 0}

    o, n = await _get(older), await _get(newer)
    # The older id survives with the better audio.
    assert o.deleted_at is None and o.status == "published"
    assert (o.quality_tier, o.audio_path) == ("lossless", f"originals/{newer}/a")
    # The recycled row holds the old copy.
    assert n.deleted_at is not None and n.duplicate_of == older
    assert (n.quality_tier, n.audio_path) == ("ok", f"originals/{older}/a")
    async with session_factory()() as s:
        comments = dict((await s.execute(select(Comment.body, Comment.position_seconds)
                                         .where(Comment.live_set_id == older))).all())
        # The older set's positions follow the new audio (shifted by the
        # swap); the newer set's were already in its timeline.
        assert comments == {"old": 100 - round(OFFSET), "new": 100}
        outcomes = (await s.execute(
            select(SetUpgradeEvent.outcome).where(SetUpgradeEvent.live_set_id == older)
            .order_by(SetUpgradeEvent.created_at)
        )).scalars().all()
        assert outcomes == ["upgraded", "merged"]
        # No per-merge notification (spec §4.7).
        assert await _count(InAppNotification, InAppNotification.kind == "set_upgraded") == 0
        fp = (await s.execute(select(SetFingerprint.raw).where(
            SetFingerprint.live_set_id == older))).scalar_one()
        assert fp == raw_to_bytes(a[TRIM:])
    assert webhooks == [(older, "set.published")]


@pytest.mark.parametrize("case", [
    "older_upgrades_off", "newer_upgrades_off", "older_kept", "newer_kept",
    "other_owner", "legacy_only", "newer_better_library_off",
])
async def test_locked_or_kept_pairs_go_to_duplicates_page(lib, case):
    a = _items(5)
    older_kw: dict = {}
    newer_kw: dict = {}
    newer_tier = "ok"
    if case == "older_upgrades_off":
        older_kw["upgrades_enabled"] = False
    elif case == "newer_upgrades_off":
        newer_kw["upgrades_enabled"] = False
    elif case == "older_kept":
        older_kw["duplicate_kept_at"] = datetime.now(UTC)
    elif case == "newer_kept":
        newer_kw["duplicate_kept_at"] = datetime.now(UTC)
    elif case == "other_owner":
        newer_kw["owner"] = await _user()
    elif case == "newer_better_library_off":
        newer_tier = "lossless"
        async with session_factory()() as s:
            (await get_config(s)).auto_upgrades_enabled = False
            await s.commit()
    if case == "legacy_only":
        # Same legacy digest, but one side has no raw fingerprint (R38).
        older = await lib.add(None, legacy_hash="same")
        newer = await lib.add(None, legacy_hash="same")
    else:
        older = await lib.add(a, **older_kw)
        newer = await lib.add(a[TRIM:], tier=newer_tier, **newer_kw)
    async with session_factory()() as s:
        s.add(Comment(live_set_id=newer, user_id=lib.owner.id, position_seconds=1, body="x"))
        await s.commit()

    try:
        assert await _cleanup() == {"merged": 0, "skipped": 1, "errors": 0}
    finally:
        if case == "newer_better_library_off":
            async with session_factory()() as s:
                (await get_config(s)).auto_upgrades_enabled = True
                await s.commit()

    o, n = await _get(older), await _get(newer)
    assert o.deleted_at is None and o.status == "published" and o.duplicate_of is None
    assert n.deleted_at is None and n.status == "published"
    assert n.duplicate_of == older and n.backfill_matched_at is not None
    assert o.audio_path == f"originals/{older}/a"
    assert await _count(Comment, Comment.live_set_id == newer) == 1

    # A re-run leaves the flagged pair alone.
    assert await _cleanup() == {"merged": 0, "skipped": 0, "errors": 0}


async def test_admin_uploaded_copy_merges_into_members_set(lib):
    a = _items(6)
    await lib.add(a)
    newer = await lib.add(a[TRIM:], owner=await _user("admin"))
    assert await _cleanup() == {"merged": 1, "skipped": 0, "errors": 0}
    assert (await _get(newer)).deleted_at is not None


async def test_different_sets_are_left_alone(lib):
    await lib.add(_items(7))
    await lib.add(_items(8))
    assert await _cleanup() == {"merged": 0, "skipped": 0, "errors": 0}
    assert await _count(LiveSet, LiveSet.deleted_at.is_not(None)) == 0


async def test_three_copies_merge_into_the_oldest(lib):
    a = _items(9)
    first = await lib.add(a)
    second = await lib.add(a[TRIM:])
    third = await lib.add(a[: len(a) - TRIM])
    assert await _cleanup() == {"merged": 2, "skipped": 0, "errors": 0}
    assert (await _get(first)).deleted_at is None
    assert (await _get(second)).duplicate_of == first
    assert (await _get(third)).duplicate_of == first


async def test_dry_run_reports_pairs_without_changing_anything(lib):
    a = _items(10)
    older = await lib.add(a)
    newer = await lib.add(a[TRIM:], tier="lossless")
    await lib.add(_items(11))
    async with session_factory()() as s:
        counts = await qb.duplicate_pair_counts(s)
        pairs = await set_merge.find_duplicate_pairs(s)
    assert counts == {"duplicate_pairs": 1, "duplicate_pairs_complete": True}
    ((o, n, result),) = pairs
    assert (o.id, n.id) == (older, newer)
    assert result.offset_seconds == pytest.approx(OFFSET, abs=0.5)
    for sid in (older, newer):
        live = await _get(sid)
        assert live.deleted_at is None and live.duplicate_of is None
        assert live.status == "published" and live.backfill_matched_at is None
    assert await _count(SetUpgradeEvent) == 0


async def test_dry_run_stops_at_its_time_budget(lib, monkeypatch):
    a = _items(12)
    await lib.add(a)
    await lib.add(a[TRIM:])
    monkeypatch.setattr(qb, "DRY_RUN_SECONDS", -1)
    async with session_factory()() as s:
        counts = await qb.duplicate_pair_counts(s)
    assert counts == {"duplicate_pairs": 0, "duplicate_pairs_complete": False}


async def test_cleanup_batch_is_resumable(lib, monkeypatch):
    from types import SimpleNamespace

    a, b = _items(13), _items(14)
    await lib.add(a)
    await lib.add(b)
    await lib.add(a[TRIM:])
    await lib.add(b[TRIM:])
    # Every deadline check after the first set is already past.
    monkeypatch.setattr(set_merge, "time", SimpleNamespace(monotonic=lambda: 10_000.0))
    totals = {"merged": 0, "skipped": 0}
    cursor, slices = None, 0
    while True:
        res = await set_merge.run_cleanup_batch(cursor=cursor, deadline=1.0)
        slices += 1
        totals["merged"] += res["merged"]
        if res["done"]:
            break
        cursor = res["cursor"]
    assert totals["merged"] == 2
    assert slices >= 4  # one set checked per slice


async def test_cleanup_sends_one_admin_summary(lib, fake_queue):
    admin1, admin2 = await _user("admin"), await _user("admin")
    member = await _user()
    a = _items(15)
    await lib.add(a, owner=admin1)
    await lib.add(a[TRIM:], owner=admin1)

    # The fill phase has nothing to do and hands over to the cleanup...
    await qb._run_quality_backfill(cleanup=True, phase="fill",
                                   counts={"fingerprinted": 3, "measured": 2})
    ((func, kwargs),) = fake_queue
    assert func == qb.JOB_FUNC
    state = kwargs["kwargs"]
    assert state["phase"] == "cleanup" and state["cleanup"] is True
    # ...which merges and notifies once.
    res = await qb._run_quality_backfill(**state)
    assert res["done"] and res["merged"] == 1
    assert len(fake_queue) == 1  # nothing more queued

    async with session_factory()() as s:
        rows = (await s.execute(select(InAppNotification).where(
            InAppNotification.kind == "maintenance"))).scalars().all()
    by_user = {r.user_id: r.payload for r in rows}
    assert admin1.id in by_user and admin2.id in by_user
    assert member.id not in by_user
    assert len([r for r in rows if r.user_id in (admin1.id, admin2.id)]) == 2
    assert by_user[admin1.id] == {"fingerprinted": 3, "measured": 2, "merged": 1, "skipped": 0}


async def test_legacy_hash_never_pairs_two_raw_fingerprints(lib):
    """Both sides comparable: the fuzzy matcher alone decides, even when
    the legacy digests happen to be equal (R28)."""
    await lib.add(_items(18), legacy_hash="same")
    await lib.add(_items(19), legacy_hash="same")
    async with session_factory()() as s:
        assert await qb.duplicate_pair_counts(s) == {
            "duplicate_pairs": 0, "duplicate_pairs_complete": True}
    assert await _cleanup() == {"merged": 0, "skipped": 0, "errors": 0}


async def test_backfill_without_cleanup_sends_nothing(lib, fake_queue):
    a = _items(16)
    await lib.add(a)
    await lib.add(a[TRIM:])
    await qb._run_quality_backfill()
    assert fake_queue == []
    assert await _count(LiveSet, LiveSet.deleted_at.is_not(None)) == 0
    assert await _count(InAppNotification, InAppNotification.kind == "maintenance") == 0


async def test_summary_skips_admins_who_turned_maintenance_off(lib):
    from setvault_core.models.identity import NotificationPreference
    from setvault_core.services.notifications import notify_backfill_summary

    on, off = await _user("admin"), await _user("admin")
    async with session_factory()() as s:
        s.add(NotificationPreference(user_id=off.id, kind="maintenance", channel="off"))
        await s.commit()
        await notify_backfill_summary(s, {"merged": 2})
        await s.commit()
        users = (await s.execute(select(InAppNotification.user_id).where(
            InAppNotification.kind == "maintenance"))).scalars().all()
    assert on.id in users and off.id not in users


# --- real audio (fpcalc; run via the Linux runner) --------------------------

async def test_backfill_with_cleanup_on_real_audio(lib, tmp_path, fake_queue, require_tools):
    """End to end on the synthetic fixture sets: an MP3 128 set and a later
    lossless copy trimmed by 20 s merge (the older id gets the FLAC); a set
    sharing only the intro, and an unrelated set, are left alone."""
    import importlib.util
    from pathlib import Path

    require_tools("ffmpeg", "ffprobe", "fpcalc")
    spec = importlib.util.spec_from_file_location(
        "fixtures_audio", Path(__file__).with_name("fixtures_audio.py"))
    fixtures_audio = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixtures_audio)
    paths = fixtures_audio.build_sets(tmp_path)
    admin = await _user("admin")

    ids = {}
    async with session_factory()() as s:
        t = datetime(2024, 1, 1, tzinfo=UTC)
        for n, name in enumerate(["a_mp3_128", "a_trim20", "b", "c"]):
            sid = uuid.uuid4()
            s.add(LiveSet(
                id=sid, slug=f"r-{sid.hex[:8]}", title=name, media_root_id=lib.root.id,
                audio_path=paths[name].name, streaming_path=f"stream/{sid}.opus",
                waveform_path=f"waveform/{sid}.json", uploaded_by=lib.owner.id,
                source_type="upload", status="published", created_at=t + timedelta(days=n),
            ))
            ids[name] = sid
        await s.flush()
        s.add_all([
            Comment(live_set_id=ids["a_mp3_128"], user_id=lib.owner.id,
                    position_seconds=100, body="old"),
            Comment(live_set_id=ids["a_trim20"], user_id=lib.owner.id,
                    position_seconds=50, body="new"),
        ])
        await s.commit()

    await qb._run_quality_backfill(cleanup=True, phase="fill")
    while fake_queue:
        _, kwargs = fake_queue.pop(0)
        await qb._run_quality_backfill(**kwargs["kwargs"])

    older, newer = await _get(ids["a_mp3_128"]), await _get(ids["a_trim20"])
    assert older.deleted_at is None and older.quality_tier == "lossless"
    assert older.audio_path == "a_trim20.flac"
    assert newer.deleted_at is not None and newer.duplicate_of == older.id
    for name in ("b", "c"):
        live = await _get(ids[name])
        assert live.deleted_at is None and live.duplicate_of is None
    async with session_factory()() as s:
        comments = dict((await s.execute(select(Comment.body, Comment.position_seconds)
                                         .where(Comment.live_set_id == older.id))).all())
        summary = (await s.execute(select(InAppNotification.payload).where(
            InAppNotification.kind == "maintenance",
            InAppNotification.user_id == admin.id))).scalars().all()
    # The trimmed copy starts 20 s into the set: the old comment moves back.
    assert comments["new"] == 50
    assert comments["old"] == pytest.approx(80, abs=1)
    assert summary == [{"fingerprinted": 4, "measured": 4, "merged": 1, "skipped": 0}]
