"""Scheduled upgrade search and "search now" (Phase 7D Task 10)."""
from __future__ import annotations

import os
import shutil
import uuid
from collections import namedtuple
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from setvault_core.db import init_engine, session_factory
from setvault_core.jobs import upgrade_search as job
from setvault_core.models.catalog import (
    Artist,
    LiveSet,
    LiveSetArtist,
    MediaRoot,
    Party,
    SetFingerprint,
)
from setvault_core.models.identity import User
from setvault_core.models.upgrades import SetUpgradeEvent
from setvault_core.models.url_rip import RipJob
from setvault_core.services.audio_match import MATCHER_VERSION
from setvault_core.services.ingest_sources import SourceRateLimitedError
from setvault_core.services.quality_profile import QualityProfile
from setvault_core.services.system_config import get_config
from setvault_ingest_sources.base import Candidate
from sqlalchemy import delete

PROFILE = QualityProfile(order=("lossless", "high", "good", "ok", "low"), cutoff="lossless")
_Usage = namedtuple("_Usage", "total used free")


@pytest.fixture(autouse=True)
def _engine():
    init_engine(os.environ["TEST_DATABASE_URL"])


def _uid() -> str:
    return uuid.uuid4().hex[:8]


def _cand(ext: str, *, title: str = "Artist X Live at Fest", uploader: str | None = None,
          duration: int | None = 3600, tier: str | None = None, kind: str = "youtube",
          ) -> Candidate:
    return Candidate(
        source_kind=kind, external_id=ext, title=title, uploader=uploader,
        duration_seconds=duration, thumbnail_url=None,
        webpage_url=f"https://www.youtube.com/watch?v={ext}", expected_tier=tier,
    )


def _live(**kw) -> LiveSet:
    """An unsaved set for the pure helpers (no artists, no party)."""
    defaults = dict(title="Artist X Live at Fest", duration_seconds=3600, quality_tier="ok",
                    audio_lossless=False)
    defaults.update(kw)
    return LiveSet(**defaults)


async def _seed_set(s, *, root: MediaRoot, user: User, fp: str = "raw", **kw) -> LiveSet:
    """``fp``: the set's fingerprint row: "raw" (current matcher version),
    "old" (an older raw version), "legacy" (hash only) or "none"."""
    defaults = dict(
        slug=f"s-{_uid()}", title="Live at Fest", media_root_id=root.id,
        audio_path=f"originals/{_uid()}.mp3", status="published", source_type="url_rip",
        uploaded_by=user.id, duration_seconds=3600, quality_tier="ok", audio_lossless=False,
        quality_measured_at=datetime.now(UTC),
    )
    defaults.update(kw)
    live = LiveSet(**defaults)
    s.add(live)
    await s.flush()
    if fp != "none":
        s.add(SetFingerprint(
            live_set_id=live.id, fingerprint_hash=_uid(), duration_seconds=3600,
            raw=None if fp == "legacy" else bytes(4000),
            raw_version=None if fp == "legacy" else (
                MATCHER_VERSION if fp == "raw" else MATCHER_VERSION - 1),
        ))
        await s.flush()
    return live


async def _seed_base(s, tmp_path: Path) -> tuple[User, MediaRoot]:
    u = User(email=f"u{_uid()}@x.test", username=f"u{_uid()}", display_name="u",
             password_hash="x")
    r = MediaRoot(name=f"r{_uid()}", host_path=str(tmp_path), enabled=True)
    s.add_all([u, r])
    await s.flush()
    return u, r


# --- due_sets ---------------------------------------------------------------


async def test_due_sets_respects_schedule_and_cutoff(session, tmp_path):
    cfg = await get_config(session)
    cfg.auto_upgrades_enabled = True
    cfg.quality_tiers_order = list(PROFILE.order)
    cfg.quality_cutoff = "high"
    u, r = await _seed_base(session, tmp_path)
    now = datetime.now(UTC)

    never = await _seed_set(session, root=r, user=u, quality_tier="ok")
    two_days = await _seed_set(session, root=r, user=u, quality_tier="good",
                               last_upgrade_search_at=now - timedelta(hours=48))
    recent = await _seed_set(session, root=r, user=u, quality_tier="ok",
                             last_upgrade_search_at=now - timedelta(hours=2))
    at_cutoff = await _seed_set(session, root=r, user=u, quality_tier="high")
    above = await _seed_set(session, root=r, user=u, quality_tier="lossless")
    switched_off = await _seed_set(session, root=r, user=u, upgrades_enabled=False)
    draft = await _seed_set(session, root=r, user=u, status="draft")
    deleted = await _seed_set(session, root=r, user=u, deleted_at=now)
    ten_days = await _seed_set(session, root=r, user=u, quality_tier="low",
                               last_upgrade_search_at=now - timedelta(days=10))
    mine = {never.id, two_days.id, recent.id, at_cutoff.id, above.id, switched_off.id,
            draft.id, deleted.id, ten_days.id}

    async def due(schedule: str) -> list[uuid.UUID]:
        rows = await job.due_sets(session, now=now, schedule=schedule, limit=10_000)
        return [x.id for x in rows if x.id in mine]

    # Daily: never-searched first, then oldest-searched.
    assert await due("daily") == [never.id, ten_days.id, two_days.id]
    # Weekly: two days ago is not due yet.
    assert await due("weekly") == [never.id, ten_days.id]
    assert await due("off") == []

    cfg.auto_upgrades_enabled = False
    assert await due("daily") == []

    # The batch limit takes the oldest first.
    cfg.auto_upgrades_enabled = True
    limited = await job.due_sets(session, now=now, schedule="daily", limit=1)
    assert len(limited) == 1


async def test_unmeasured_set_is_not_searched(session, tmp_path):
    """A set whose quality has not been measured yet has no tier to beat."""
    cfg = await get_config(session)
    cfg.auto_upgrades_enabled = True
    cfg.quality_tiers_order = list(PROFILE.order)
    cfg.quality_cutoff = "lossless"
    u, r = await _seed_base(session, tmp_path)
    unmeasured = await _seed_set(session, root=r, user=u, quality_tier=None,
                                 quality_measured_at=None)
    rows = await job.due_sets(session, now=datetime.now(UTC), schedule="daily", limit=10_000)
    assert unmeasured.id not in {x.id for x in rows}


async def test_due_sets_needs_a_current_raw_fingerprint_and_no_duplicate_link(
    session, tmp_path,
):
    """R28: a set the matcher can't compare against (no raw, or an older
    matcher version) would reject every genuine upgrade, and a kept duplicate
    is not the set to upgrade; neither is searched."""
    cfg = await get_config(session)
    cfg.auto_upgrades_enabled = True
    cfg.quality_tiers_order = list(PROFILE.order)
    cfg.quality_cutoff = "lossless"
    u, r = await _seed_base(session, tmp_path)
    ok = await _seed_set(session, root=r, user=u)
    no_fp = await _seed_set(session, root=r, user=u, fp="none")
    legacy = await _seed_set(session, root=r, user=u, fp="legacy")
    old = await _seed_set(session, root=r, user=u, fp="old")
    kept_dup = await _seed_set(session, root=r, user=u, duplicate_of=ok.id)
    rows = await job.due_sets(session, now=datetime.now(UTC), schedule="daily", limit=10_000)
    found = {x.id for x in rows} & {ok.id, no_fp.id, legacy.id, old.id, kept_dup.id}
    assert found == {ok.id}


# --- build_query / pick_candidate ---------------------------------------------


async def test_build_query_uses_main_artists_title_and_party(session, tmp_path):
    u, r = await _seed_base(session, tmp_path)
    a1 = Artist(name="Artist  X", slug=f"a-{_uid()}")
    a2 = Artist(name="Guest", slug=f"a-{_uid()}")
    p = Party(name="Fest\t2024", slug=f"p-{_uid()}")
    session.add_all([a1, a2, p])
    await session.flush()
    live = await _seed_set(session, root=r, user=u, title=" Live  at Fest ", party_id=p.id)
    session.add_all([
        LiveSetArtist(live_set_id=live.id, artist_id=a1.id, position=0, role="main"),
        LiveSetArtist(live_set_id=live.id, artist_id=a2.id, position=1, role="b2b_guest"),
    ])
    await session.flush()
    session.expunge(live)
    live = await session.get(LiveSet, live.id)
    assert job.build_query(live) == "Artist X Live at Fest Fest 2024"


def test_pick_candidate_prefers_known_better_then_soundboard(monkeypatch):
    monkeypatch.setattr(job, "build_query", lambda live: "Artist X Fest")
    live = _live()
    maybe = _cand("maybe", tier=None)
    good = _cand("good", tier="good")
    lossless = _cand("lossless", tier="lossless")
    lossless_sbd = _cand("lossless-sbd", tier="lossless", title="Artist X Fest SBD")
    not_better = _cand("same", tier="ok")
    worse = _cand("worse", tier="low")

    pick = job.pick_candidate(live, [maybe, worse, not_better, good, lossless, lossless_sbd],
                              profile=PROFILE, tried=set())
    assert pick is lossless_sbd       # best tier, soundboard breaks the tie
    pick = job.pick_candidate(live, [maybe, good, lossless], profile=PROFILE, tried=set())
    assert pick is lossless           # rank beats search order
    pick = job.pick_candidate(live, [maybe, good], profile=PROFILE, tried=set())
    assert pick is good               # known-better before maybe
    sbd_maybe = _cand("maybe-sbd", title="Artist X Fest soundboard")
    pick = job.pick_candidate(live, [maybe, sbd_maybe], profile=PROFILE, tried=set())
    assert pick is sbd_maybe          # among maybes, the hint breaks the tie
    pick = job.pick_candidate(live, [maybe, _cand("maybe2")], profile=PROFILE, tried=set())
    assert pick is maybe              # then search order
    # Equal or worse expected tiers never qualify on their own.
    assert job.pick_candidate(live, [not_better, worse], profile=PROFILE, tried=set()) is None


def test_pick_candidate_skips_tried_and_wrong_duration(monkeypatch):
    monkeypatch.setattr(job, "build_query", lambda live: "Artist X Fest")
    live = _live(duration_seconds=3600)
    tried = _cand("tried", tier="lossless")
    too_short = _cand("short", tier="lossless", duration=3600 - 400)   # > 10 %
    too_long = _cand("long", tier="lossless", duration=3600 + 400)
    wrong_title = _cand("title", tier="lossless", title="Someone Else at Fest")
    ok = _cand("ok", tier="high", duration=3600 - 300)                  # within 10 %
    pick = job.pick_candidate(
        live, [tried, too_short, too_long, wrong_title, ok], profile=PROFILE,
        tried={("youtube", "tried")},
    )
    assert pick is ok

    # Short sets get the 120 s floor instead of 10 %.
    short = _live(duration_seconds=600)
    assert job.pick_candidate(short, [_cand("a", duration=700)], profile=PROFILE,
                              tried=set()) is not None
    assert job.pick_candidate(short, [_cand("b", duration=730)], profile=PROFILE,
                              tried=set()) is None
    # A source that reports no duration (Internet Archive) is not ruled out;
    # the fingerprint match on the download decides.
    assert job.pick_candidate(live, [_cand("c", duration=None)], profile=PROFILE,
                              tried=set()) is not None

    # A lossy copy never replaces a lossless one, even one rated lower.
    flac = _live(quality_tier="good", audio_lossless=True)
    assert job.pick_candidate(flac, [_cand("d", tier="high")], profile=PROFILE,
                              tried=set()) is None


# --- search_upgrade_for_set ---------------------------------------------------


@pytest.fixture
async def seeded(tmp_path):
    """A committed published MP3 set below the cutoff, plus cleanup."""
    async with session_factory()() as s:
        cfg = await get_config(s)
        saved = (cfg.auto_upgrades_enabled, list(cfg.quality_tiers_order), cfg.quality_cutoff)
        cfg.auto_upgrades_enabled = True
        cfg.quality_tiers_order = list(PROFILE.order)
        cfg.quality_cutoff = "lossless"
        u, r = await _seed_base(s, tmp_path)
        live = await _seed_set(s, root=r, user=u, title="Artist X Live at Fest",
                               source_url="https://www.youtube.com/watch?v=own",
                               source_external_id="own")
        await s.commit()
        ids = {"set": live.id, "user": u.id, "root": r.id}
    yield ids
    async with session_factory()() as s:
        await s.execute(delete(RipJob).where(RipJob.upgrade_target_set_id == ids["set"]))
        await s.execute(delete(SetUpgradeEvent).where(SetUpgradeEvent.live_set_id == ids["set"]))
        await s.execute(delete(LiveSet).where(LiveSet.id == ids["set"]))
        await s.execute(delete(User).where(User.id == ids["user"]))
        await s.execute(delete(MediaRoot).where(MediaRoot.id == ids["root"]))
        cfg = await get_config(s)
        cfg.auto_upgrades_enabled, cfg.quality_tiers_order, cfg.quality_cutoff = saved
        await s.commit()


@pytest.fixture
def sources(monkeypatch):
    """Stub the source search and rip submission; plenty of disk by default."""
    state = {"results": [], "raise": None, "searched": [], "submitted": [], "enqueued": [],
             "attempted": [], "submit_errors": {}}

    async def fake_kinds(session):
        return ["youtube"]

    async def fake_search(session, *, kind, query, limit):
        state["searched"].append((kind, query))
        if state["raise"] is not None:
            raise state["raise"]
        return list(state["results"])

    async def fake_submit(session, **kw):
        state["attempted"].append(kw["url"])
        if (err := state["submit_errors"].get(kw["url"])) is not None:
            raise err
        state["submitted"].append(kw)
        rip = RipJob(submitted_by=kw["user_id"], source_url=kw["url"], status="queued",
                     progress_pct=0, probed_metadata={},
                     upgrade_target_set_id=kw["upgrade_target_set_id"], trigger=kw["trigger"])
        session.add(rip)
        await session.flush()
        return rip

    monkeypatch.setattr(job, "_enabled_kinds", fake_kinds)
    monkeypatch.setattr(job, "search_source", fake_search)
    monkeypatch.setattr(job, "submit_rip", fake_submit)
    monkeypatch.setattr(job, "_enqueue_rip", lambda rip_id: state["enqueued"].append(rip_id))
    monkeypatch.setattr(shutil, "disk_usage", lambda p: _Usage(10**13, 0, 10**13))
    return state


async def _stamp(set_id: uuid.UUID) -> datetime | None:
    async with session_factory()() as s:
        return (await s.get(LiveSet, set_id)).last_upgrade_search_at


async def test_search_upgrade_submits_targeted_rip(seeded, sources):
    own = _cand("own", tier=None)          # the set's own source: never re-ripped
    better = _cand("better", tier="lossless")
    sources["results"] = [own, better]
    async with session_factory()() as s:
        outcome = await job.search_upgrade_for_set(s, seeded["set"], trigger="scheduled")
    assert outcome == "queued"
    assert sources["searched"] == [("youtube", "Artist X Live at Fest")]
    [sub] = sources["submitted"]
    assert sub == {"user_id": seeded["user"], "url": better.webpage_url,
                   "upgrade_target_set_id": seeded["set"], "trigger": "scheduled"}
    assert len(sources["enqueued"]) == 1
    assert await _stamp(seeded["set"]) is not None

    # The next sweep doesn't download the same candidate again.
    sources["submitted"].clear()
    async with session_factory()() as s:
        assert await job.search_upgrade_for_set(
            s, seeded["set"], trigger="scheduled") == "no_candidate"
    assert sources["submitted"] == []


async def test_search_upgrade_skips_candidates_already_rejected(seeded, sources):
    async with session_factory()() as s:
        s.add(SetUpgradeEvent(live_set_id=seeded["set"], trigger="scheduled",
                              outcome="rejected", reason="audio differs",
                              candidate_source_kind="youtube", candidate_external_id="seen"))
        await s.commit()
    sources["results"] = [_cand("seen", tier="lossless")]
    async with session_factory()() as s:
        assert await job.search_upgrade_for_set(
            s, seeded["set"], trigger="scheduled") == "no_candidate"
    assert sources["submitted"] == []
    assert await _stamp(seeded["set"]) is not None


async def test_rate_limited_set_is_not_stamped(seeded, sources):
    sources["raise"] = SourceRateLimitedError("youtube")
    async with session_factory()() as s:
        outcome = await job.search_upgrade_for_set(s, seeded["set"], trigger="scheduled")
    assert outcome == "rate_limited"
    assert sources["submitted"] == []
    assert await _stamp(seeded["set"]) is None


async def test_low_disk_space_skips_submit(seeded, sources, monkeypatch):
    monkeypatch.setattr(shutil, "disk_usage",
                        lambda p: _Usage(10**12, 10**12, job.UPGRADE_MIN_FREE_BYTES - 1))
    sources["results"] = [_cand("better", tier="lossless")]
    async with session_factory()() as s:
        outcome = await job.search_upgrade_for_set(s, seeded["set"], trigger="scheduled")
    assert outcome == "no_space"
    assert sources["submitted"] == []
    assert await _stamp(seeded["set"]) is None


async def test_search_now_ignores_the_library_switch_but_not_the_set_switch(seeded, sources):
    async with session_factory()() as s:
        (await get_config(s)).auto_upgrades_enabled = False
        await s.commit()
    sources["results"] = [_cand("better", tier="lossless")]
    async with session_factory()() as s:
        assert await job.search_upgrade_for_set(
            s, seeded["set"], trigger="scheduled") == "not_eligible"
    async with session_factory()() as s:
        assert await job.search_upgrade_for_set(
            s, seeded["set"], trigger="search_now") == "queued"
    assert sources["submitted"][0]["trigger"] == "search_now"

    async with session_factory()() as s:
        (await s.get(LiveSet, seeded["set"])).upgrades_enabled = False
        await s.commit()
    async with session_factory()() as s:
        assert await job.search_upgrade_for_set(
            s, seeded["set"], trigger="search_now") == "not_eligible"


def test_run_upgrade_search_stops_the_batch_when_rate_limited(monkeypatch):
    ids = [uuid.uuid4() for _ in range(3)]
    seen: list[uuid.UUID] = []

    async def fake_due(session, *, now, schedule, limit):
        assert limit == job.UPGRADE_SEARCH_BATCH
        return [LiveSet(id=i) for i in ids]

    async def fake_search(session, live_set_id, *, trigger):
        assert trigger == "scheduled"
        seen.append(live_set_id)
        return "queued" if len(seen) == 1 else "rate_limited"

    monkeypatch.setattr(job, "due_sets", fake_due)
    monkeypatch.setattr(job, "search_upgrade_for_set", fake_search)
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    summary = job.run_upgrade_search()
    assert seen == ids[:2]
    assert summary["queued"] == 1 and summary["rate_limited"] == 1


async def test_submit_rip_records_the_upgrade_target(monkeypatch):
    from unittest.mock import AsyncMock, MagicMock

    from setvault_core.services import url_rip

    monkeypatch.setattr(url_rip, "probe_url", lambda url: url_rip.ProbeResult(
        platform="soundcloud", external_id=None, title="t", duration_seconds=None,
        uploader=None, thumbnail_url=None, webpage_url=url, raw={},
    ))
    session = MagicMock()
    session.flush = AsyncMock()
    target = uuid.uuid4()
    rip = await url_rip.submit_rip(session, user_id=uuid.uuid4(), url="https://soundcloud.com/a/b",
                                   upgrade_target_set_id=target, trigger="search_now")
    assert (rip.upgrade_target_set_id, rip.trigger) == (target, "search_now")


# --- review round 1 -------------------------------------------------------------


async def test_already_ripped_candidates_do_not_use_up_the_attempts(seeded, sources):
    from setvault_core.services.url_rip import DuplicateRipError

    dups = [_cand(f"dup{i}", tier="lossless") for i in range(3)]
    fresh = _cand("fresh", tier="high")
    sources["results"] = [*dups, fresh]
    for c in dups:
        sources["submit_errors"][c.webpage_url] = DuplicateRipError(RipJob())
    async with session_factory()() as s:
        outcome = await job.search_upgrade_for_set(s, seeded["set"], trigger="scheduled")
    assert outcome == "queued"
    assert [x["url"] for x in sources["submitted"]] == [fresh.webpage_url]


async def test_probe_failure_is_recorded_and_skipped_next_run(seeded, sources):
    from sqlalchemy import select

    broken = _cand("geo", tier="lossless")
    sources["results"] = [broken]
    sources["submit_errors"][broken.webpage_url] = ValueError("Video unavailable in your country")
    async with session_factory()() as s:
        assert await job.search_upgrade_for_set(
            s, seeded["set"], trigger="scheduled") == "no_candidate"
    async with session_factory()() as s:
        [event] = (await s.execute(select(SetUpgradeEvent).where(
            SetUpgradeEvent.live_set_id == seeded["set"]))).scalars().all()
    assert (event.outcome, event.candidate_source_kind, event.candidate_external_id) == (
        "rejected", "youtube", "geo")
    assert event.reason.startswith("probe failed: Video unavailable")

    sources["attempted"].clear()
    async with session_factory()() as s:
        assert await job.search_upgrade_for_set(
            s, seeded["set"], trigger="scheduled") == "no_candidate"
    assert sources["attempted"] == []


async def test_probe_failures_are_capped_per_set(seeded, sources):
    broken = [_cand(f"b{i}", tier="lossless") for i in range(job._MAX_SUBMIT_ATTEMPTS + 1)]
    sources["results"] = broken
    for c in broken:
        sources["submit_errors"][c.webpage_url] = ValueError("private")
    async with session_factory()() as s:
        assert await job.search_upgrade_for_set(
            s, seeded["set"], trigger="scheduled") == "no_candidate"
    assert len(sources["attempted"]) == job._MAX_SUBMIT_ATTEMPTS


def test_run_upgrade_search_stops_starting_sets_when_out_of_time(monkeypatch):
    ids = [uuid.uuid4() for _ in range(4)]
    seen: list[uuid.UUID] = []
    clock = {"t": 1000.0}

    async def fake_due(session, *, now, schedule, limit):
        return [LiveSet(id=i) for i in ids]

    async def fake_search(session, live_set_id, *, trigger):
        seen.append(live_set_id)
        clock["t"] += job.UPGRADE_SEARCH_BATCH_BUDGET_SECONDS / 2   # each set takes 10 min
        return "no_candidate"

    monkeypatch.setattr(job, "due_sets", fake_due)
    monkeypatch.setattr(job, "search_upgrade_for_set", fake_search)
    monkeypatch.setattr(job, "_clock", lambda: clock["t"])
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    summary = job.run_upgrade_search()
    assert seen == ids[:2]
    assert summary["searched"] == 2 and summary["deferred"] == 2


def test_enqueue_search_upgrade_now_skips_while_in_flight(monkeypatch):
    from rq import Queue
    from rq.job import Job

    status = {"value": None}
    enqueued: list[dict] = []

    class FakeJob:
        def get_status(self, refresh=True):
            return status["value"]

    monkeypatch.setattr(Job, "fetch_many", staticmethod(
        lambda ids, connection: [FakeJob() if status["value"] else None]))
    monkeypatch.setattr(Queue, "enqueue", lambda self, func, **kw: enqueued.append(
        {"func": func, **kw}))

    set_id = uuid.uuid4()
    assert job.enqueue_search_upgrade_now(set_id) is True
    assert enqueued == [{
        "func": "setvault_core.jobs.upgrade_search.run_search_upgrade_now",
        "live_set_id": str(set_id), "job_id": f"upgrade-search-now-{set_id}",
        "job_timeout": job.SEARCH_NOW_JOB_TIMEOUT,
    }]
    for in_flight in ("queued", "started"):
        status["value"] = in_flight
        assert job.enqueue_search_upgrade_now(set_id) is False
    status["value"] = "finished"
    assert job.enqueue_search_upgrade_now(set_id) is True
    assert len(enqueued) == 2
