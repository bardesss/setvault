"""Swap service (Phase 7D Task 7): a better copy's audio moves into an
existing set; the old copy goes to the recycle bin."""
from __future__ import annotations

import os
import shutil
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from setvault_core.db import init_engine, session_factory
from setvault_core.models.catalog import LiveSet, MediaRoot, SetFingerprint
from setvault_core.models.engagement import ListeningHistory, UserSetState
from setvault_core.models.engagement_3c import Bookmark, Comment, InAppNotification
from setvault_core.models.identity import User
from setvault_core.models.tracklist import TracklistEntry
from setvault_core.models.upgrades import SetUpgradeEvent
from setvault_core.services import set_upgrade
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture(autouse=True)
def _engine():
    init_engine(os.environ["TEST_DATABASE_URL"])


@pytest.fixture
def webhooks(monkeypatch):
    calls: list[tuple[uuid.UUID, str]] = []

    async def fake(live, event):
        calls.append((live.id, event))

    monkeypatch.setattr(set_upgrade, "fan_out_webhooks", fake)
    return calls


def _touch(root: Path, rel: str, data: bytes) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)


async def _seed(tmp_path: Path, *, offset: float | None = None) -> dict:
    """A published target (MP3, with context) and a processed lossless arrival."""
    async with session_factory()() as s:
        u = User(email=f"u{uuid.uuid4().hex[:6]}@x.test", username=f"u{uuid.uuid4().hex[:6]}",
                 display_name="u", password_hash="x")
        r = MediaRoot(name=f"r{uuid.uuid4().hex[:6]}", host_path=str(tmp_path), enabled=True)
        s.add_all([u, r])
        await s.flush()
        tid, aid = uuid.uuid4(), uuid.uuid4()
        target = LiveSet(
            id=tid, slug=f"target-{tid.hex[:6]}", title="Set X", media_root_id=r.id,
            audio_path=f"originals/{tid}/old.mp3", streaming_path=f"stream/{tid}.opus",
            waveform_path=f"waveform/{tid}.json", duration_seconds=3600,
            normalized_lufs=-14.0, uploaded_by=u.id, status="published",
            source_type="url_rip", source_url="https://youtube.example/old",
            source_external_id="yt-old", audio_codec="mp3", audio_bitrate_kbps=128,
            audio_sample_rate=44100, audio_bit_depth=None, audio_lossless=False,
            quality_tier="ok", quality_measured_at=datetime.now(UTC),
        )
        arrival = LiveSet(
            id=aid, slug=f"arrival-{aid.hex[:6]}", title="Set X (Bandcamp)",
            media_root_id=r.id, audio_path=f"originals/{aid}/new.flac",
            streaming_path=f"stream/{aid}.opus", waveform_path=f"waveform/{aid}.json",
            duration_seconds=3590, normalized_lufs=-9.5, uploaded_by=u.id, status="draft",
            source_type="url_rip", source_url="https://bandcamp.example/new",
            source_external_id="bc-new", audio_codec="flac", audio_bitrate_kbps=900,
            audio_sample_rate=48000, audio_bit_depth=24, audio_lossless=True,
            quality_tier="lossless", quality_measured_at=datetime.now(UTC),
            duplicate_of=tid, match_offset_seconds=offset,
        )
        s.add_all([target, arrival])
        await s.flush()
        s.add_all([
            SetFingerprint(live_set_id=tid, fingerprint_hash="old-hash", duration_seconds=3600.0,
                           raw=b"old", raw_version=1),
            SetFingerprint(live_set_id=aid, fingerprint_hash="new-hash", duration_seconds=3590.0,
                           raw=b"new", raw_version=1),
            TracklistEntry(live_set_id=tid, position=0, start_seconds=0, end_seconds=5,
                           raw_label="intro", created_by=u.id),
            TracklistEntry(live_set_id=tid, position=1, start_seconds=60, end_seconds=None,
                           raw_label="track 2", created_by=u.id),
            Comment(live_set_id=tid, user_id=u.id, position_seconds=120, body="drop!"),
            Comment(live_set_id=tid, user_id=u.id, position_seconds=None, body="general"),
            Bookmark(live_set_id=tid, user_id=u.id, position_seconds=300, label="b"),
            UserSetState(user_id=u.id, live_set_id=tid, position_seconds=1000.5),
            ListeningHistory(user_id=u.id, live_set_id=tid, last_position_seconds=2.0),
        ])
        await s.commit()
    for rel, data in (
        (f"originals/{tid}/old.mp3", b"OLD-AUDIO"), (f"stream/{tid}.opus", b"OLD-STREAM"),
        (f"waveform/{tid}.json", b"OLD-WAVE"), (f"originals/{aid}/new.flac", b"NEW-AUDIO"),
        (f"stream/{aid}.opus", b"NEW-STREAM"), (f"waveform/{aid}.json", b"NEW-WAVE"),
    ):
        _touch(tmp_path, rel, data)
    return {"user": u.id, "target": tid, "arrival": aid, "slug": target.slug}


async def _apply(s: AsyncSession, ids: dict, **kw) -> SetUpgradeEvent:
    target = await s.get(LiveSet, ids["target"])
    arrival = await s.get(LiveSet, ids["arrival"])
    return await set_upgrade.apply_upgrade(
        s, target=target, arrival=arrival, trigger="scheduled",
        candidate_source_kind="bandcamp", candidate_external_id="bc-new", **kw,
    )


async def test_swap_moves_audio_and_keeps_context(tmp_path: Path, webhooks):
    ids = await _seed(tmp_path)
    async with session_factory()() as s:
        event = await _apply(s, ids)
    assert event.outcome == "upgraded"

    tid, aid = ids["target"], ids["arrival"]
    async with session_factory()() as s:
        t = await s.get(LiveSet, tid)
        a = await s.get(LiveSet, aid)
        # Target: same row and slug, new audio + quality + source.
        assert t.slug == ids["slug"] and t.title == "Set X" and t.status == "published"
        assert t.deleted_at is None
        assert (t.audio_path, t.streaming_path, t.waveform_path) == (
            f"originals/{aid}/new.flac", f"stream/{aid}.opus", f"waveform/{aid}.json")
        assert (t.quality_tier, t.audio_codec, t.audio_lossless, t.audio_bit_depth) == (
            "lossless", "flac", True, 24)
        assert (t.duration_seconds, t.normalized_lufs) == (3590, -9.5)
        assert (t.source_url, t.source_external_id) == ("https://bandcamp.example/new", "bc-new")
        # Arrival: recycled, holding the old copy.
        assert (a.audio_path, a.streaming_path, a.waveform_path) == (
            f"originals/{tid}/old.mp3", f"stream/{tid}.opus", f"waveform/{tid}.json")
        assert (a.quality_tier, a.audio_codec, a.audio_bitrate_kbps) == ("ok", "mp3", 128)
        assert a.source_url == "https://youtube.example/old"
        assert (a.duration_seconds, a.normalized_lufs) == (3600, -14.0)
        # R31: still a duplicate of the target, so a restore lands on the
        # Duplicates page rather than as an invisible draft.
        assert a.status == "draft" and a.duplicate_of == tid
        assert a.title == "Set X (replaced copy)"
        assert a.deleted_at is not None
        assert a.purge_after_at - a.deleted_at == timedelta(days=14)
        # Context stays on the target.
        tl = (await s.execute(select(TracklistEntry).where(
            TracklistEntry.live_set_id == tid).order_by(TracklistEntry.position))).scalars().all()
        assert [e.raw_label for e in tl] == ["intro", "track 2"]
        assert [e.start_seconds for e in tl] == [0, 60]  # no offset → unchanged
        comments = (await s.execute(select(Comment).where(Comment.live_set_id == tid))).scalars()
        assert len(comments.all()) == 2
        bm = (await s.execute(select(Bookmark).where(Bookmark.live_set_id == tid))).scalars()
        assert len(bm.all()) == 1
        # Fingerprints swapped with the audio.
        t_fp = (await s.execute(select(SetFingerprint).where(
            SetFingerprint.live_set_id == tid))).scalars().all()
        a_fp = (await s.execute(select(SetFingerprint).where(
            SetFingerprint.live_set_id == aid))).scalars().all()
        assert [f.fingerprint_hash for f in t_fp] == ["new-hash"]
        assert [f.fingerprint_hash for f in a_fp] == ["old-hash"]
        # History event.
        ev = (await s.execute(select(SetUpgradeEvent).where(
            SetUpgradeEvent.live_set_id == tid))).scalars().one()
        assert (ev.outcome, ev.trigger) == ("upgraded", "scheduled")
        assert (ev.from_tier, ev.from_codec, ev.from_bitrate_kbps) == ("ok", "mp3", 128)
        assert ev.from_source_url == "https://youtube.example/old"
        assert (ev.to_tier, ev.to_codec, ev.to_source_url) == (
            "lossless", "flac", "https://bandcamp.example/new")
        assert (ev.candidate_source_kind, ev.candidate_external_id) == ("bandcamp", "bc-new")
        # Owner notified in-app.
        notes = (await s.execute(select(InAppNotification).where(
            InAppNotification.user_id == ids["user"]))).scalars().all()
        assert [(n.kind, n.subject_id) for n in notes] == [("set_upgraded", tid)]
        assert notes[0].payload["set_slug"] == ids["slug"]
        assert notes[0].payload["set_title"] == "Set X"
    # Files untouched; webhooks fired for the target after commit.
    assert (tmp_path / f"originals/{tid}/old.mp3").read_bytes() == b"OLD-AUDIO"
    assert (tmp_path / f"originals/{aid}/new.flac").read_bytes() == b"NEW-AUDIO"
    assert webhooks == [(tid, "set.published")]


async def test_swap_shifts_positions_by_offset(tmp_path: Path, webhooks):
    # The arrival starts 10.4 s into the set: existing t <-> arrival t - 10.4.
    ids = await _seed(tmp_path, offset=10.4)
    async with session_factory()() as s:
        event = await _apply(s, ids)
    assert event.offset_seconds == pytest.approx(10.4)

    tid, uid_ = ids["target"], ids["user"]
    async with session_factory()() as s:
        tl = (await s.execute(select(TracklistEntry).where(
            TracklistEntry.live_set_id == tid).order_by(TracklistEntry.position))).scalars().all()
        assert [(e.start_seconds, e.end_seconds) for e in tl] == [(0, 0), (50, None)]
        cs = (await s.execute(select(Comment).where(Comment.live_set_id == tid))).scalars().all()
        assert sorted(c.position_seconds for c in cs if c.position_seconds is not None) == [110]
        assert any(c.position_seconds is None for c in cs)  # NULL stays NULL
        bm = (await s.execute(select(Bookmark).where(Bookmark.live_set_id == tid))).scalar_one()
        assert bm.position_seconds == 290
        st = await s.get(UserSetState, (uid_, tid))
        assert st.position_seconds == pytest.approx(990.1)
        lh = (await s.execute(select(ListeningHistory).where(
            ListeningHistory.live_set_id == tid))).scalar_one()
        assert lh.last_position_seconds == 0  # 2.0 - 10.4 clamps at 0


async def test_swap_negative_offset_shifts_later(tmp_path: Path, webhooks):
    ids = await _seed(tmp_path, offset=-5.0)
    async with session_factory()() as s:
        await _apply(s, ids)
    async with session_factory()() as s:
        tl = (await s.execute(select(TracklistEntry).where(
            TracklistEntry.live_set_id == ids["target"])
            .order_by(TracklistEntry.position))).scalars().all()
        assert [(e.start_seconds, e.end_seconds) for e in tl] == [(5, 10), (65, None)]


async def test_swap_rounds_half_offsets_up(tmp_path: Path, webhooks):
    # 2.5 s: round-half-up shifts int positions by 3 (banker's rounding: 2).
    ids = await _seed(tmp_path, offset=2.5)
    async with session_factory()() as s:
        await _apply(s, ids)
    async with session_factory()() as s:
        bm = (await s.execute(select(Bookmark).where(
            Bookmark.live_set_id == ids["target"]))).scalar_one()
        assert bm.position_seconds == 297
        st = await s.get(UserSetState, (ids["user"], ids["target"]))
        assert st.position_seconds == pytest.approx(998.0)  # floats shift exactly


async def test_swap_clamps_positions_to_the_new_duration(tmp_path: Path, webhooks):
    # The new copy (3590 s) starts 20 s earlier: late positions would land
    # past its end and are clamped to it.
    ids = await _seed(tmp_path, offset=-20.0)
    async with session_factory()() as s:
        s.add(Comment(live_set_id=ids["target"], user_id=ids["user"],
                      position_seconds=3580, body="encore"))
        st = await s.get(UserSetState, (ids["user"], ids["target"]))
        st.position_seconds = 3585.5
        await s.commit()
    async with session_factory()() as s:
        await _apply(s, ids)
    async with session_factory()() as s:
        cs = (await s.execute(select(Comment).where(
            Comment.live_set_id == ids["target"]))).scalars().all()
        assert sorted(c.position_seconds for c in cs if c.position_seconds is not None) == [
            140, 3590,
        ]
        st = await s.get(UserSetState, (ids["user"], ids["target"]))
        assert st.position_seconds == pytest.approx(3590.0)


async def test_swap_ignores_sub_second_offset(tmp_path: Path, webhooks):
    ids = await _seed(tmp_path, offset=0.6)
    async with session_factory()() as s:
        await _apply(s, ids)
    async with session_factory()() as s:
        bm = (await s.execute(select(Bookmark).where(
            Bookmark.live_set_id == ids["target"]))).scalar_one()
        assert bm.position_seconds == 300
        st = await s.get(UserSetState, (ids["user"], ids["target"]))
        assert st.position_seconds == pytest.approx(1000.5)


async def test_swap_failure_leaves_target_on_old_files(tmp_path: Path, webhooks, monkeypatch):
    ids = await _seed(tmp_path, offset=10.0)
    tid, aid = ids["target"], ids["arrival"]
    async with session_factory()() as s:
        real_commit = s.commit
        calls = {"n": 0}

        async def flaky_commit():
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("db went away")
            await real_commit()

        monkeypatch.setattr(s, "commit", flaky_commit)
        with pytest.raises(RuntimeError, match="db went away"):
            await _apply(s, ids)

    assert webhooks == []
    async with session_factory()() as s:
        t = await s.get(LiveSet, tid)
        a = await s.get(LiveSet, aid)
        assert t.audio_path == f"originals/{tid}/old.mp3"
        assert t.streaming_path == f"stream/{tid}.opus"
        assert t.quality_tier == "ok"
        assert a.audio_path == f"originals/{aid}/new.flac" and a.deleted_at is None
        for rel in (t.audio_path, t.streaming_path, t.waveform_path,
                    a.audio_path, a.streaming_path, a.waveform_path):
            assert (tmp_path / rel).exists()
        fp = (await s.execute(select(SetFingerprint).where(
            SetFingerprint.live_set_id == tid))).scalar_one()
        assert fp.fingerprint_hash == "old-hash"
        bm = (await s.execute(select(Bookmark).where(Bookmark.live_set_id == tid))).scalar_one()
        assert bm.position_seconds == 300  # shift rolled back too
        evs = (await s.execute(select(SetUpgradeEvent).where(
            SetUpgradeEvent.live_set_id == tid))).scalars().all()
        assert evs == []


async def test_swap_does_no_file_io(tmp_path: Path, webhooks, monkeypatch):
    ids = await _seed(tmp_path)

    def boom(*a, **k):
        raise AssertionError("apply_upgrade touched the filesystem")

    for name in ("unlink", "rename", "replace", "rmdir"):
        monkeypatch.setattr(Path, name, boom)
    for name in ("remove", "unlink", "rename", "replace", "rmdir"):
        monkeypatch.setattr(os, name, boom)
    monkeypatch.setattr(shutil, "move", boom)
    monkeypatch.setattr(shutil, "rmtree", boom)
    async with session_factory()() as s:
        await _apply(s, ids)


async def test_notification_failure_does_not_undo_swap(tmp_path: Path, webhooks, monkeypatch):
    ids = await _seed(tmp_path)

    async def broken(*a, **k):
        raise RuntimeError("bell is broken")

    monkeypatch.setattr(set_upgrade, "notify_set_upgraded", broken)
    async with session_factory()() as s:
        await _apply(s, ids)
    async with session_factory()() as s:
        t = await s.get(LiveSet, ids["target"])
        assert t.quality_tier == "lossless"
    assert webhooks == [(ids["target"], "set.published")]


async def test_swap_rejects_bad_input(tmp_path: Path, webhooks):
    ids = await _seed(tmp_path)
    async with session_factory()() as s:
        target = await s.get(LiveSet, ids["target"])
        arrival = await s.get(LiveSet, ids["arrival"])
        with pytest.raises(ValueError):
            await set_upgrade.apply_upgrade(s, target=target, arrival=target, trigger="upload")
        arrival.waveform_path = None
        with pytest.raises(ValueError):
            await set_upgrade.apply_upgrade(s, target=target, arrival=arrival, trigger="upload")


async def test_restoring_recycled_old_copy_does_not_touch_target(tmp_path: Path, webhooks):
    ids = await _seed(tmp_path)
    async with session_factory()() as s:
        await _apply(s, ids)
    tid, aid = ids["target"], ids["arrival"]
    async with session_factory()() as s:
        # What POST /api/admin/recycle/{slug}/restore does.
        a = await s.get(LiveSet, aid)
        a.deleted_at = None
        a.purge_after_at = None
        await s.commit()
    async with session_factory()() as s:
        t = await s.get(LiveSet, tid)
        a = await s.get(LiveSet, aid)
        assert (t.audio_path, t.streaming_path, t.waveform_path) == (
            f"originals/{aid}/new.flac", f"stream/{aid}.opus", f"waveform/{aid}.json")
        assert t.status == "published" and t.deleted_at is None
        # The restored copy is a separate draft set with the old audio.
        assert a.audio_path == f"originals/{tid}/old.mp3" and a.status == "draft"
        assert a.duplicate_of == tid
    assert (tmp_path / f"originals/{aid}/new.flac").exists()
    assert (tmp_path / f"originals/{tid}/old.mp3").exists()


async def test_discard_arrival_records_rejection_and_removes_files(tmp_path: Path):
    ids = await _seed(tmp_path, offset=3.0)
    tid, aid = ids["target"], ids["arrival"]
    async with session_factory()() as s:
        target = await s.get(LiveSet, tid)
        arrival = await s.get(LiveSet, aid)
        await set_upgrade.discard_arrival(
            s, arrival, target=target, trigger="scheduled", reason="different audio",
            candidate_source_kind="bandcamp", candidate_external_id="bc-new",
        )
    async with session_factory()() as s:
        assert await s.get(LiveSet, aid) is None
        t = await s.get(LiveSet, tid)
        assert t.audio_path == f"originals/{tid}/old.mp3" and t.quality_tier == "ok"
        ev = (await s.execute(select(SetUpgradeEvent).where(
            SetUpgradeEvent.live_set_id == tid))).scalars().one()
        assert (ev.outcome, ev.reason, ev.trigger) == ("rejected", "different audio", "scheduled")
        assert (ev.candidate_source_kind, ev.candidate_external_id) == ("bandcamp", "bc-new")
        assert (ev.from_tier, ev.to_tier) == ("ok", "lossless")
        assert ev.offset_seconds == pytest.approx(3.0)
        fps = (await s.execute(select(SetFingerprint).where(
            SetFingerprint.live_set_id == aid))).scalars().all()
        assert fps == []
    for rel in (f"originals/{aid}/new.flac", f"stream/{aid}.opus", f"waveform/{aid}.json"):
        assert not (tmp_path / rel).exists()
    assert not (tmp_path / f"originals/{aid}").exists()
    for rel in (f"originals/{tid}/old.mp3", f"stream/{tid}.opus", f"waveform/{tid}.json"):
        assert (tmp_path / rel).exists()


async def test_discard_arrival_without_target(tmp_path: Path):
    ids = await _seed(tmp_path)
    async with session_factory()() as s:
        arrival = await s.get(LiveSet, ids["arrival"])
        await set_upgrade.discard_arrival(
            s, arrival, target=None, trigger="upload", reason="not better")
    async with session_factory()() as s:
        assert await s.get(LiveSet, ids["arrival"]) is None
        evs = (await s.execute(select(SetUpgradeEvent))).scalars().all()
        assert evs == []
    assert not (tmp_path / f"originals/{ids['arrival']}/new.flac").exists()


async def test_discard_arrival_refuses_published_set(tmp_path: Path):
    ids = await _seed(tmp_path)
    async with session_factory()() as s:
        target = await s.get(LiveSet, ids["target"])
        with pytest.raises(ValueError):
            await set_upgrade.discard_arrival(
                s, target, target=None, trigger="upload", reason="x")
    assert (tmp_path / f"originals/{ids['target']}/old.mp3").exists()


async def test_discard_arrival_keeps_files_another_set_uses(tmp_path: Path):
    ids = await _seed(tmp_path)
    async with session_factory()() as s:
        arrival = await s.get(LiveSet, ids["arrival"])
        target = await s.get(LiveSet, ids["target"])
        arrival.streaming_path = target.streaming_path  # shared by mistake
        await s.commit()
        await set_upgrade.discard_arrival(
            s, arrival, target=target, trigger="upload", reason="x")
    assert (tmp_path / f"stream/{ids['target']}.opus").exists()
    assert not (tmp_path / f"originals/{ids['arrival']}/new.flac").exists()


# --- R15/R16 + webhook gating (fix round) ----------------------------------


async def test_purge_of_recycled_copy_spares_files_the_live_target_now_uses(
    tmp_path: Path, webhooks,
):
    """R15: a later transcode regen of the target writes stream/<target-id>.opus,
    the very path the recycled old copy holds. Purging that copy must not
    delete it."""
    from setvault_core.jobs.recycle_bin_purge import purge_recycle_bin

    ids = await _seed(tmp_path)
    tid, aid = ids["target"], ids["arrival"]
    async with session_factory()() as s:
        await _apply(s, ids)
    regen = f"stream/{tid}.opus"
    async with session_factory()() as s:
        t = await s.get(LiveSet, tid)
        t.streaming_path = regen
        a = await s.get(LiveSet, aid)
        a.purge_after_at = datetime.now(UTC) - timedelta(minutes=1)
        await s.commit()
    _touch(tmp_path, regen, b"REGEN-STREAM")

    res = await purge_recycle_bin()
    assert res == {"purged": 1, "errors": 0}

    async with session_factory()() as s:
        assert await s.get(LiveSet, aid) is None
        t = await s.get(LiveSet, tid)
        assert t.streaming_path == regen and t.deleted_at is None
    assert (tmp_path / regen).read_bytes() == b"REGEN-STREAM"
    assert (tmp_path / f"originals/{aid}/new.flac").exists()  # target's audio
    # Files only the recycled row referenced are gone.
    assert not (tmp_path / f"originals/{tid}/old.mp3").exists()
    assert not (tmp_path / f"waveform/{tid}.json").exists()
    # The recycled copy's audio lived under the target's id: that now-empty
    # dir goes too, the dir holding the target's live audio stays.
    assert not (tmp_path / f"originals/{tid}").exists()
    assert (tmp_path / "originals").is_dir()
    assert (tmp_path / "waveform").is_dir()


async def test_plain_purge_still_deletes_unreferenced_files(tmp_path: Path):
    from setvault_core.jobs.recycle_bin_purge import purge_recycle_bin

    ids = await _seed(tmp_path)
    aid = ids["arrival"]
    async with session_factory()() as s:
        a = await s.get(LiveSet, aid)
        a.deleted_at = datetime.now(UTC) - timedelta(days=15)
        a.purge_after_at = datetime.now(UTC) - timedelta(days=1)
        await s.commit()

    assert await purge_recycle_bin() == {"purged": 1, "errors": 0}
    for rel in (f"originals/{aid}/new.flac", f"stream/{aid}.opus", f"waveform/{aid}.json"):
        assert not (tmp_path / rel).exists()
    assert not (tmp_path / f"originals/{aid}").exists()
    assert (tmp_path / f"originals/{ids['target']}/old.mp3").exists()


async def test_swap_repoints_rip_job_to_target(tmp_path: Path, webhooks):
    from setvault_core.models.url_rip import RipJob

    ids = await _seed(tmp_path)
    async with session_factory()() as s:
        job = RipJob(
            submitted_by=ids["user"], source_url="https://bandcamp.example/new",
            status="done", progress_pct=100, live_set_id=ids["arrival"],
            created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
        )
        s.add(job)
        await s.commit()
        job_id = job.id
    async with session_factory()() as s:
        await _apply(s, ids)
    async with session_factory()() as s:
        assert (await s.get(RipJob, job_id)).live_set_id == ids["target"]


async def test_swap_repoints_duplicates_and_unmatched_files_to_target(
    tmp_path: Path, webhooks,
):
    """Rows that pointed at the arrival (a later held duplicate of it, a
    watch-folder file resolved to it) follow the audio to the target."""
    from setvault_core.models.watch_folder import UnmatchedFile, WatchFolder

    ids = await _seed(tmp_path)
    tid, aid = ids["target"], ids["arrival"]
    async with session_factory()() as s:
        target = await s.get(LiveSet, tid)
        twin = LiveSet(slug=f"twin-{uuid.uuid4().hex[:6]}", title="twin",
                       media_root_id=target.media_root_id, audio_path="originals/x/t.mp3",
                       uploaded_by=ids["user"], status="draft", duplicate_of=aid)
        wf = WatchFolder(name=f"wf{uuid.uuid4().hex[:6]}", host_path=str(tmp_path / "in"),
                         target_media_root_id=target.media_root_id)
        s.add_all([twin, wf])
        await s.flush()
        uf = UnmatchedFile(watch_folder_id=wf.id, file_path="in/new.flac",
                           resolution="linked_to_set", resolved_to_set_id=aid)
        s.add(uf)
        await s.commit()
        twin_id, uf_id, wf_id = twin.id, uf.id, wf.id
    try:
        async with session_factory()() as s:
            await _apply(s, ids)
        async with session_factory()() as s:
            assert (await s.get(LiveSet, twin_id)).duplicate_of == tid
            assert (await s.get(UnmatchedFile, uf_id)).resolved_to_set_id == tid
            # The recycled old copy itself still points at the target.
            assert (await s.get(LiveSet, aid)).duplicate_of == tid
    finally:
        async with session_factory()() as s:
            await s.delete(await s.get(LiveSet, twin_id))
            await s.delete(await s.get(WatchFolder, wf_id))
            await s.commit()


async def test_draft_target_upgrade_fires_no_webhook(tmp_path: Path, webhooks):
    ids = await _seed(tmp_path)
    async with session_factory()() as s:
        t = await s.get(LiveSet, ids["target"])
        t.status = "draft"
        await s.commit()
    async with session_factory()() as s:
        await _apply(s, ids)
    assert webhooks == []
    async with session_factory()() as s:
        assert (await s.get(LiveSet, ids["target"])).quality_tier == "lossless"


async def test_published_target_upgrade_fires_webhook(tmp_path: Path, webhooks):
    ids = await _seed(tmp_path)
    async with session_factory()() as s:
        await _apply(s, ids)
    assert webhooks == [(ids["target"], "set.published")]


# --- review fix round 1 ------------------------------------------------------


async def test_discard_arrival_keeps_its_rip_job(tmp_path: Path):
    from setvault_core.models.url_rip import RipJob

    ids = await _seed(tmp_path)
    async with session_factory()() as s:
        job = RipJob(
            submitted_by=ids["user"], source_url="https://bandcamp.example/new",
            status="waveform", progress_pct=90, live_set_id=ids["arrival"],
            created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
        )
        s.add(job)
        await s.commit()
        job_id = job.id
    async with session_factory()() as s:
        arrival = await s.get(LiveSet, ids["arrival"])
        target = await s.get(LiveSet, ids["target"])
        await set_upgrade.discard_arrival(
            s, arrival, target=target, trigger="url_rip", reason="not better")
    async with session_factory()() as s:
        job = await s.get(RipJob, job_id)
        assert job is not None and job.live_set_id is None
        assert await s.get(LiveSet, ids["arrival"]) is None


async def test_discard_arrival_refuses_a_recycled_row(tmp_path: Path, webhooks):
    ids = await _seed(tmp_path)
    async with session_factory()() as s:
        await _apply(s, ids)  # the arrival now holds the old copy, soft-deleted
    async with session_factory()() as s:
        recycled = await s.get(LiveSet, ids["arrival"])
        with pytest.raises(ValueError):
            await set_upgrade.discard_arrival(
                s, recycled, target=None, trigger="url_rip", reason="x")
    async with session_factory()() as s:
        assert await s.get(LiveSet, ids["arrival"]) is not None
    tid = ids["target"]
    for rel in (f"originals/{tid}/old.mp3", f"stream/{tid}.opus"):
        assert (tmp_path / rel).exists()


async def test_second_apply_for_same_arrival_is_refused(tmp_path: Path, webhooks):
    ids = await _seed(tmp_path, offset=10.0)
    async with session_factory()() as s:
        await _apply(s, ids)
    # A second caller tries the same arrival again.
    async with session_factory()() as s:
        with pytest.raises(set_upgrade.UpgradeNoLongerApplicable):
            await _apply(s, ids)
    tid, aid = ids["target"], ids["arrival"]
    async with session_factory()() as s:
        t = await s.get(LiveSet, tid)
        assert t.audio_path == f"originals/{aid}/new.flac"
        bm = (await s.execute(select(Bookmark).where(Bookmark.live_set_id == tid))).scalar_one()
        assert bm.position_seconds == 290  # shifted exactly once
        evs = (await s.execute(select(SetUpgradeEvent).where(
            SetUpgradeEvent.live_set_id == tid))).scalars().all()
        assert len(evs) == 1
        fp = (await s.execute(select(SetFingerprint).where(
            SetFingerprint.live_set_id == tid))).scalar_one()
        assert fp.fingerprint_hash == "new-hash"
    assert len(webhooks) == 1


async def test_apply_rechecks_state_from_the_db(tmp_path: Path, webhooks):
    """The caller's in-memory rows are stale (loaded before another worker
    recycled the target); the locked re-read must catch it."""
    ids = await _seed(tmp_path)
    async with session_factory()() as s:
        target = await s.get(LiveSet, ids["target"])
        arrival = await s.get(LiveSet, ids["arrival"])
        await s.commit()  # end the read transaction, as a worker would
        async with session_factory()() as other:
            t2 = await other.get(LiveSet, ids["target"])
            t2.deleted_at = datetime.now(UTC)
            await other.commit()
        assert target.deleted_at is None  # stale view
        with pytest.raises(set_upgrade.UpgradeNoLongerApplicable):
            await set_upgrade.apply_upgrade(s, target=target, arrival=arrival, trigger="upload")
    async with session_factory()() as s:
        a = await s.get(LiveSet, ids["arrival"])
        assert a.audio_path == f"originals/{ids['arrival']}/new.flac" and a.deleted_at is None
    assert webhooks == []
