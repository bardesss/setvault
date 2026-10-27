"""Library cleanup: merge published sets that are the same audio (Phase 7D
spec §4.7).

The quality backfill gives older sets a raw fingerprint, so duplicates that
were published before fuzzy matching existed become visible. For each such
pair (older set O, newer set N) the cleanup either

- **merges** them: O survives (it keeps its id, slug and page). When N has
  the strictly better audio, O first gets N's audio through the normal swap
  (``apply_upgrade``); either way everything users attached to N (comments,
  bookmarks, play history and positions, favourites, notes, tracklist when O
  has none, artists and tags O lacks...) moves to O, and N goes to the
  recycle bin; or
- **skips** them: N stays published, gets ``duplicate_of = O`` and
  ``backfill_matched_at``, and is listed on the admin Duplicates page as
  "matched by backfill". That happens when either set has upgrades off or
  was explicitly kept, the owners differ (R20), the quality of either is
  unknown, the newer copy is better but the swap isn't allowed, or the match
  rests on the legacy exact hash only (R38: only fuzzy-confirmed matches
  between two current raw fingerprints merge automatically).

The survivor is always the older set, so a resumable scan can walk the sets
oldest first and treat each one as the "newer" side against everything
before it.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import Text, and_, case, cast, delete, func, literal, select, update
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_core import triggers
from setvault_core.db import session_factory
from setvault_core.models.catalog import LiveSet, LiveSetArtist, LiveSetTag, SetFingerprint
from setvault_core.models.engagement import Favorite, ListeningHistory, UserSetState
from setvault_core.models.engagement_3c import Bookmark, Comment, InAppNotification, PrivateNote
from setvault_core.models.enrichment import ResolveJob
from setvault_core.models.tracklist import TracklistEntry, TracklistImportJob
from setvault_core.models.upgrades import SetUpgradeEvent
from setvault_core.models.url_rip import RipJob
from setvault_core.models.watch_folder import UnmatchedFile
from setvault_core.services.audio_match import (
    MatchResult,
    compare,
    current_fingerprint,
    is_same_audio,
    raw_from_bytes,
)
from setvault_core.services.audit import log as audit_log
from setvault_core.services.quality_profile import get_profile
from setvault_core.services.set_match import (
    DURATION_TOLERANCE_PCT,
    DURATION_TOLERANCE_SECONDS,
    LEGACY_DURATION_SECONDS,
    LEGACY_EXACT_MATCH,
)
from setvault_core.services.set_upgrade import (
    MIN_SHIFT_SECONDS,
    RECYCLE_GRACE,
    UpgradeNoLongerApplicable,
    _lock_sets,
    apply_upgrade,
    audio_is_better,
    build_upgrade_event,
    event_audio,
    may_replace_audio,
    upgrade_refusal,
    whole_seconds,
)
from setvault_core.services.webhook_events import announce_recycled

logger = logging.getLogger(__name__)

TRIGGER = triggers.BACKFILL
REASON_BACKFILL = "matched by backfill"
TRACKLIST_KEPT = "tracklist kept with the recycled copy"
_MERGED_SUFFIX = " (merged copy)"
_TITLE_MAX = 512  # LiveSet.title is String(512)
# Raw fingerprints kept in memory during one scan (a 2-hour set is ~230 KB).
_RAW_CACHE_BYTES = 128 * 1024 * 1024


# --------------------------------------------------------------------------
# Finding pairs
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class _Fp:
    id: uuid.UUID
    hash: str
    duration: float
    current: bool  # raw present and comparable (current MATCHER_VERSION)


@dataclass
class _Entry:
    id: uuid.UUID
    created_at: datetime
    fps: list[_Fp]

    @property
    def key(self) -> tuple[datetime, uuid.UUID]:
        return (self.created_at, self.id)

    def current_fp(self) -> _Fp | None:
        return next((f for f in self.fps if f.current), None)


@dataclass(frozen=True)
class DuplicatePair:
    older_id: uuid.UUID
    newer_id: uuid.UUID
    # For compare(older, newer): offset > 0 means the newer copy starts later.
    result: MatchResult
    # True: confirmed by the fuzzy matcher on two current raw fingerprints.
    # False: only the legacy exact hash matched (never merged automatically).
    fuzzy: bool


class _DeadlineReached(Exception):
    pass


def _eligible():
    """Sets that take part in the cleanup: published, live, not themselves
    a known duplicate (held, kept, or already matched by the backfill)."""
    return and_(
        LiveSet.status == "published",
        LiveSet.deleted_at.is_(None),
        LiveSet.duplicate_of.is_(None),
    )


async def _load_index(session: AsyncSession) -> list[_Entry]:
    """Eligible sets with fingerprint metadata (no raw blobs), oldest first."""
    rows = (await session.execute(
        select(
            LiveSet.id, LiveSet.created_at, SetFingerprint.id,
            SetFingerprint.fingerprint_hash, SetFingerprint.duration_seconds,
            current_fingerprint(),
        )
        .join(SetFingerprint, SetFingerprint.live_set_id == LiveSet.id)
        .where(_eligible())
        .order_by(LiveSet.created_at, LiveSet.id,
                  SetFingerprint.created_at, SetFingerprint.id)
    )).all()
    entries: list[_Entry] = []
    by_id: dict[uuid.UUID, _Entry] = {}
    for set_id, created_at, fp_id, fp_hash, duration, current in rows:
        entry = by_id.get(set_id)
        if entry is None:
            entry = by_id[set_id] = _Entry(set_id, created_at, [])
            entries.append(entry)
        entry.fps.append(_Fp(fp_id, fp_hash, float(duration), bool(current)))
    return entries


class _RawCache:
    """Raw fingerprints by SetFingerprint id, least recently used evicted
    past a byte budget. A row's raw never changes (a swap only moves the row
    to another set), so entries stay valid across merges."""

    def __init__(self, session: AsyncSession, budget: int = _RAW_CACHE_BYTES) -> None:
        self._session = session
        self._budget = budget
        self._size = 0
        self._items: OrderedDict[uuid.UUID, tuple] = OrderedDict()

    async def get(self, fp_id: uuid.UUID):
        """The raw fingerprint, or None when the row is gone (its set was
        purged since the index was loaded)."""
        hit = self._items.get(fp_id)
        if hit is not None:
            self._items.move_to_end(fp_id)
            return hit[0]
        raw = (await self._session.execute(
            select(SetFingerprint.raw).where(SetFingerprint.id == fp_id)
        )).scalar_one_or_none()
        if raw is None:
            return None
        fp = raw_from_bytes(raw)
        self._items[fp_id] = (fp, len(raw))
        self._size += len(raw)
        while self._size > self._budget and len(self._items) > 1:
            _, (_, size) = self._items.popitem(last=False)
            self._size -= size
        return fp


async def _match(older: _Entry, newer: _Entry, cache: _RawCache,
                 ) -> tuple[MatchResult, bool] | None:
    o_cur, n_cur = older.current_fp(), newer.current_fp()
    if o_cur is not None and n_cur is not None:
        # Both comparable: the fuzzy matcher alone decides (as R28).
        tol = max(DURATION_TOLERANCE_PCT * n_cur.duration, DURATION_TOLERANCE_SECONDS)
        if abs(o_cur.duration - n_cur.duration) > tol:
            return None
        a, b = await cache.get(o_cur.id), await cache.get(n_cur.id)
        if a is None or b is None:
            return None  # a side was purged meanwhile: no match
        # compare() is CPU-bound pure Python; keep the event loop free.
        result = await asyncio.to_thread(compare, a, b)
        return (result, True) if is_same_audio(result) else None
    # One side has no current raw fingerprint: the pre-7D exact rule (same
    # 120 s digest, duration within 2 s). Only ever sends a pair to the
    # Duplicates page (R38).
    if any(
        a.hash == b.hash and abs(a.duration - b.duration) < LEGACY_DURATION_SECONDS
        for a in older.fps for b in newer.fps
    ):
        return LEGACY_EXACT_MATCH, False
    return None


async def _find_older(index: list[_Entry], i: int, cache: _RawCache,
                      deadline: float | None = None) -> DuplicatePair | None:
    """The earliest set before ``index[i]`` that is the same audio."""
    newer = index[i]
    for older in index[:i]:
        if deadline is not None and time.monotonic() >= deadline:
            raise _DeadlineReached
        hit = await _match(older, newer, cache)
        if hit is not None:
            return DuplicatePair(older.id, newer.id, hit[0], hit[1])
    return None


async def scan_duplicate_pairs(
    session: AsyncSession, *, deadline: float | None = None,
) -> tuple[list[DuplicatePair], bool]:
    """All (older, newer) same-audio pairs among published sets; each newer
    set pairs with the earliest set it matches. Changes nothing. Returns
    ``(pairs, complete)``; ``complete`` is False when ``deadline``
    (``time.monotonic()`` value) cut the scan short."""
    index = await _load_index(session)
    cache = _RawCache(session)
    pairs: list[DuplicatePair] = []
    try:
        for i in range(len(index)):
            pair = await _find_older(index, i, cache, deadline)
            if pair is not None:
                pairs.append(pair)
    except _DeadlineReached:
        return pairs, False
    return pairs, True


# --------------------------------------------------------------------------
# Deciding a pair
# --------------------------------------------------------------------------

def _is_eligible(live: LiveSet | None) -> bool:
    return (live is not None and live.status == "published"
            and live.deleted_at is None and live.duplicate_of is None)


async def _skip_reason(
    session: AsyncSession, older: LiveSet, newer: LiveSet, pair: DuplicatePair,
) -> str | None:
    """Why this pair must not be merged automatically, or None."""
    if not pair.fuzzy:
        return "legacy fingerprint only"
    if not older.upgrades_enabled or not newer.upgrades_enabled:
        return "upgrades off"
    if older.duplicate_kept_at is not None or newer.duplicate_kept_at is not None:
        return "kept"
    if older.quality_tier is None or newer.quality_tier is None:
        return "quality unknown"
    if audio_is_better(await get_profile(session), newer, older):
        # The swap's own rules (library switch, owner R20, quality).
        if not newer.streaming_path or not newer.waveform_path:
            return "not processed"
        return await upgrade_refusal(session, newer, older, trigger=TRIGGER)
    # Plain merge: the newer set's content moves into the older one; same
    # owner rule as a swap (its uploader owns the survivor, or is an admin).
    if not await may_replace_audio(session, newer, older):
        return "not owner"
    return None


async def _mark_skipped(
    session: AsyncSession, older: LiveSet, newer: LiveSet, pair: DuplicatePair, reason: str,
) -> None:
    newer.duplicate_of = older.id
    newer.match_offset_seconds = pair.result.offset_seconds if pair.fuzzy else None
    newer.backfill_matched_at = datetime.now(UTC)
    await audit_log(
        session, actor_user_id=None, actor_kind="system",
        action="set.backfill_matched", target_type="LiveSet", target_id=str(newer.id),
        after={"duplicate_of": str(older.id), "reason": reason, "fuzzy": pair.fuzzy},
    )


async def resolve_pair(pair: DuplicatePair) -> str:
    """Merge or skip one pair found by the scan. Returns ``"merged"``,
    ``"skipped"`` or ``"stale"`` (one side changed since the scan)."""
    async with session_factory()() as s:
        locked = await _lock_sets(s, pair.older_id, pair.newer_id)
        older, newer = locked.get(pair.older_id), locked.get(pair.newer_id)
        if not _is_eligible(older) or not _is_eligible(newer):
            await s.rollback()
            return "stale"
        if pair.fuzzy:
            # Re-check under the lock: a swap since the scan may have given
            # the older set other audio (and another offset).
            result = await _confirm_match(s, older.id, newer.id)
            if result is None:
                await s.rollback()
                return "stale"
            pair = DuplicatePair(pair.older_id, pair.newer_id, result, True)
        reason = await _skip_reason(s, older, newer, pair)
        if reason is not None:
            await _mark_skipped(s, older, newer, pair, reason)
            await s.commit()
            return "skipped"

        if not audio_is_better(await get_profile(s), newer, older):
            await merge_pair(s, survivor=older, loser=newer,
                             offset_seconds=pair.result.offset_seconds)
            return "merged"

        # The newer copy is better: the older set (the one users know) takes
        # its audio, then the newer row's context moves over, in one
        # transaction. The newer set's positions are already in the new
        # audio's timeline, so they move unshifted; the older set's own
        # positions are shifted by the swap.
        newer.match_offset_seconds = pair.result.offset_seconds
        await s.flush()

        async def _merge(target: LiveSet, arrival: LiveSet) -> None:
            await _merge_rows(s, survivor=target, loser=arrival,
                              offset_seconds=0.0, after_upgrade=True)

        try:
            await apply_upgrade(s, target=older, arrival=newer, trigger=TRIGGER,
                                notify=False, before_commit=_merge)
        except UpgradeNoLongerApplicable as exc:
            # Rolled back (match_offset_seconds too); the state changed
            # since the checks above. Leave the pair for review.
            return await _skip_after_refusal(pair, str(exc))
        return "merged"


async def _confirm_match(
    session: AsyncSession, older_id: uuid.UUID, newer_id: uuid.UUID,
) -> MatchResult | None:
    raws = []
    for set_id in (older_id, newer_id):
        raw = (await session.execute(
            select(SetFingerprint.raw).where(
                SetFingerprint.live_set_id == set_id,
                current_fingerprint(),
            ).order_by(SetFingerprint.created_at, SetFingerprint.id).limit(1)
        )).scalar_one_or_none()
        if raw is None:
            return None
        raws.append(raw_from_bytes(raw))
    result = await asyncio.to_thread(compare, raws[0], raws[1])
    return result if is_same_audio(result) else None


async def _skip_after_refusal(pair: DuplicatePair, reason: str) -> str:
    async with session_factory()() as s:
        locked = await _lock_sets(s, pair.older_id, pair.newer_id)
        older, newer = locked.get(pair.older_id), locked.get(pair.newer_id)
        if not _is_eligible(older) or not _is_eligible(newer):
            await s.rollback()
            return "stale"
        await _mark_skipped(s, older, newer, pair, reason)
        await s.commit()
        return "skipped"


# --------------------------------------------------------------------------
# Merging
# --------------------------------------------------------------------------

def _shifted(col, delta: float, *, nullable: bool, upper: float | None = None):
    """``col + delta`` clamped at 0 and, when known, at ``upper`` (the
    survivor's duration); NULL stays NULL (GREATEST ignores NULLs and would
    turn them into 0)."""
    expr = func.greatest(col + delta, 0)
    if upper is not None:
        expr = func.least(expr, upper)
    if nullable:
        return case((col.is_(None), None), else_=expr)
    return expr


async def _repoint(session: AsyncSession, model, fk, survivor_id, loser_id,
                   shifts=(), upper: float | None = None) -> int:
    """Move ``model`` rows from the loser to the survivor, shifting the
    given ``(column, delta, nullable)`` positions on the way (clamped to
    ``0..upper``)."""
    values = {fk.key: survivor_id}
    for col, delta, nullable in shifts:
        values[col.key] = _shifted(col, delta, nullable=nullable, upper=upper)
    res = await session.execute(
        update(model).where(fk == loser_id).values(values)
        .execution_options(synchronize_session=False)
    )
    return res.rowcount or 0


async def _merge_rows(
    session: AsyncSession, *, survivor: LiveSet, loser: LiveSet,
    offset_seconds: float, after_upgrade: bool = False, trigger: str = TRIGGER,
) -> SetUpgradeEvent:
    """Move the loser's context to the survivor and recycle the loser. Runs
    inside the caller's transaction (both rows locked) and doesn't commit.

    ``offset_seconds`` is where the loser's audio starts within the
    survivor's: a position ``t`` on the loser becomes ``t + offset`` on the
    survivor (clamped to 0 and, when known, the survivor's duration). Rows
    that describe the loser's own copy stay with it: its fingerprints (they
    belong to its audio), and its artists and tags (copied, so a restored
    copy is complete).
    """
    s_id, l_id = survivor.id, loser.id
    off = offset_seconds if abs(offset_seconds) >= MIN_SHIFT_SECONDS else 0.0
    whole = whole_seconds(off)
    # Shifted positions stay inside the survivor's audio (when its length is known).
    upper = survivor.duration_seconds
    moved: dict[str, int] = {}

    # Metadata: add what the survivor lacks; the loser keeps its own rows.
    s_artists = select(LiveSetArtist.artist_id).where(LiveSetArtist.live_set_id == s_id)
    max_pos = (await session.execute(
        select(func.coalesce(func.max(LiveSetArtist.position), -1))
        .where(LiveSetArtist.live_set_id == s_id)
    )).scalar_one()
    new_artists = (await session.execute(
        select(LiveSetArtist.artist_id, LiveSetArtist.role)
        .where(LiveSetArtist.live_set_id == l_id, LiveSetArtist.artist_id.not_in(s_artists))
        .order_by(LiveSetArtist.position)
    )).all()
    for n, (artist_id, role) in enumerate(new_artists, start=1):
        await session.execute(pg_insert(LiveSetArtist).values(
            live_set_id=s_id, artist_id=artist_id, position=max_pos + n, role=role,
        ).on_conflict_do_nothing())
    moved["artists"] = len(new_artists)
    res = await session.execute(
        pg_insert(LiveSetTag).from_select(
            ["live_set_id", "tag_id"],
            select(literal(s_id, PG_UUID(as_uuid=True)), LiveSetTag.tag_id)
            .where(LiveSetTag.live_set_id == l_id),
        ).on_conflict_do_nothing()
    )
    moved["tags"] = res.rowcount or 0

    # Per-user rows (one per user and set).
    res = await session.execute(
        pg_insert(Favorite).from_select(
            ["user_id", "live_set_id", "created_at"],
            select(Favorite.user_id, literal(s_id, PG_UUID(as_uuid=True)), Favorite.created_at)
            .where(Favorite.live_set_id == l_id),
        ).on_conflict_do_nothing()
    )
    moved["favorites"] = res.rowcount or 0
    await session.execute(delete(Favorite).where(Favorite.live_set_id == l_id)
                          .execution_options(synchronize_session=False))

    moved["play_state"] = await _merge_user_state(session, s_id, l_id, off, upper)
    moved["notes"] = await _merge_notes(session, s_id, l_id)

    # Rows that simply belong to the set: repoint, shifting positions.
    moved["history"] = await _repoint(
        session, ListeningHistory, ListeningHistory.live_set_id, s_id, l_id,
        [(ListeningHistory.last_position_seconds, off, False)] if off else (), upper)
    moved["comments"] = await _repoint(
        session, Comment, Comment.live_set_id, s_id, l_id,
        [(Comment.position_seconds, whole, True)] if whole else (), upper)
    moved["bookmarks"] = await _repoint(
        session, Bookmark, Bookmark.live_set_id, s_id, l_id,
        [(Bookmark.position_seconds, whole, True)] if whole else (), upper)
    for model, fk, name in (
        (ResolveJob, ResolveJob.live_set_id, "resolve_jobs"),
        (TracklistImportJob, TracklistImportJob.live_set_id, "tracklist_imports"),
        (RipJob, RipJob.live_set_id, "rips"),
        (RipJob, RipJob.upgrade_target_set_id, "upgrade_rips"),
        (UnmatchedFile, UnmatchedFile.resolved_to_set_id, "unmatched_files"),
        (SetUpgradeEvent, SetUpgradeEvent.live_set_id, "upgrade_events"),
    ):
        moved[name] = await _repoint(session, model, fk, s_id, l_id)

    # Tracklist: only into a survivor that has none (spec §4.7); otherwise
    # it stays with the recycled copy and the history says so.
    s_has_tracklist = (await session.execute(
        select(func.count()).select_from(TracklistEntry)
        .where(TracklistEntry.live_set_id == s_id)
    )).scalar_one() > 0
    if s_has_tracklist:
        l_entries = (await session.execute(
            select(func.count()).select_from(TracklistEntry)
            .where(TracklistEntry.live_set_id == l_id)
        )).scalar_one()
        tracklist = "kept" if l_entries else "none"
        moved["tracklist"] = 0
    else:
        moved["tracklist"] = await _repoint(
            session, TracklistEntry, TracklistEntry.live_set_id, s_id, l_id,
            [(TracklistEntry.start_seconds, whole, False),
             (TracklistEntry.end_seconds, whole, True)] if whole else (), upper)
        tracklist = "moved" if moved["tracklist"] else "none"

    # Other copies held as duplicates of the loser now point at the
    # survivor; their offsets were relative to the loser's audio.
    res = await session.execute(
        update(LiveSet).where(LiveSet.duplicate_of == l_id, LiveSet.id != l_id)
        .values(
            duplicate_of=s_id,
            match_offset_seconds=case(
                (LiveSet.match_offset_seconds.is_(None), None),
                else_=LiveSet.match_offset_seconds + off,
            ),
        )
        .execution_options(synchronize_session=False)
    )
    moved["duplicates"] = res.rowcount or 0

    # Bell entries about the loser link to the survivor's page instead.
    await session.execute(
        update(InAppNotification)
        .where(InAppNotification.subject_type == "set",
               InAppNotification.subject_id == l_id)
        .values(subject_id=s_id)
        .execution_options(synchronize_session=False)
    )
    await session.execute(
        update(InAppNotification)
        .where(InAppNotification.payload["set_slug"].astext == loser.slug)
        .values(payload=func.jsonb_set(
            InAppNotification.payload,
            cast(literal("{set_slug}"), ARRAY(Text)),
            func.to_jsonb(cast(literal(survivor.slug), Text)),
        ))
        .execution_options(synchronize_session=False)
    )

    # The loser goes to the recycle bin as a duplicate of the survivor, so
    # a restore lands on the Duplicates page (as after a swap, R31).
    # Not shared with apply_upgrade's recycle block: the title, suffix and
    # match_offset_seconds differ.
    now = datetime.now(UTC)
    if not after_upgrade:
        base = loser.title[: _TITLE_MAX - len(_MERGED_SUFFIX)]
        loser.title = f"{base}{_MERGED_SUFFIX}"
        loser.status = "draft"
        loser.duplicate_of = s_id
        loser.match_offset_seconds = offset_seconds
        loser.deleted_at = now
        loser.purge_after_at = now + RECYCLE_GRACE
    loser.backfill_matched_at = None

    # History: "from" is the merged copy as users knew it (after a swap that
    # is the audio the survivor now has), "to" the survivor's audio.
    merged_copy = survivor if after_upgrade else loser
    # Just after the transaction's now(), i.e. after the swap's own
    # "upgraded" event in the same transaction (server default now()).
    db_now = (await session.execute(select(func.now()))).scalar_one()
    event = build_upgrade_event(
        live_set_id=s_id, trigger=trigger, outcome="merged",
        reason=TRACKLIST_KEPT if tracklist == "kept" else None,
        **event_audio("from", merged_copy), **event_audio("to", survivor),
        offset_seconds=offset_seconds,
        created_at=db_now + timedelta(milliseconds=1),
    )
    session.add(event)
    await audit_log(
        session, actor_user_id=None, actor_kind="system",
        action="set.duplicate_merged", target_type="LiveSet", target_id=str(s_id),
        after={
            "merged_set_id": str(l_id), "merged_set_slug": loser.slug,
            "upgraded": after_upgrade, "offset_seconds": offset_seconds, "trigger": trigger,
            "tracklist": tracklist, "moved": moved,
        },
    )
    await session.flush()
    logger.info("merged set %s into %s (%s)", l_id, s_id, moved)
    return event


async def _merge_user_state(session: AsyncSession, s_id, l_id, off: float,
                            upper: float | None = None) -> int:
    """Playback position per user: move the loser's; where the user has one
    on both sets, keep the more recently updated. Shifted positions are
    clamped to ``0..upper``."""
    s_users = select(UserSetState.user_id).where(UserSetState.live_set_id == s_id)
    res = await session.execute(
        update(UserSetState)
        .where(UserSetState.live_set_id == l_id, UserSetState.user_id.not_in(s_users))
        .values(
            live_set_id=s_id,
            position_seconds=_shifted(UserSetState.position_seconds, off,
                                      nullable=False, upper=upper),
            # Keep the timestamp: it decides future collisions.
            updated_at=UserSetState.updated_at,
        )
        .execution_options(synchronize_session=False)
    )
    count = res.rowcount or 0
    both = (await session.execute(
        select(UserSetState.user_id, UserSetState.position_seconds,
               UserSetState.playback_rate, UserSetState.completed, UserSetState.updated_at)
        .where(UserSetState.live_set_id == l_id)
    )).all()
    for user_id, position, rate, completed, updated_at in both:
        newer = await session.execute(
            update(UserSetState)
            .where(UserSetState.live_set_id == s_id, UserSetState.user_id == user_id,
                   UserSetState.updated_at < updated_at)
            .values(position_seconds=_clamp(position + off, upper), playback_rate=rate,
                    completed=completed, updated_at=updated_at)
            .execution_options(synchronize_session=False)
        )
        count += newer.rowcount or 0
    await session.execute(delete(UserSetState).where(UserSetState.live_set_id == l_id)
                          .execution_options(synchronize_session=False))
    return count


def _clamp(position: float, upper: float | None) -> float:
    position = max(position, 0.0)
    return position if upper is None else min(position, float(upper))


async def _merge_notes(session: AsyncSession, s_id, l_id) -> int:
    """Private notes: move the loser's; where a user wrote on both sets, the
    loser's text is appended so no note is lost."""
    s_users = select(PrivateNote.user_id).where(PrivateNote.live_set_id == s_id)
    res = await session.execute(
        update(PrivateNote)
        .where(PrivateNote.live_set_id == l_id, PrivateNote.user_id.not_in(s_users))
        .values(live_set_id=s_id, updated_at=PrivateNote.updated_at)
        .execution_options(synchronize_session=False)
    )
    count = res.rowcount or 0
    both = (await session.execute(
        select(PrivateNote.user_id, PrivateNote.body_md, PrivateNote.updated_at)
        .where(PrivateNote.live_set_id == l_id)
    )).all()
    for user_id, body, updated_at in both:
        mine = (await session.execute(
            select(PrivateNote.body_md, PrivateNote.updated_at)
            .where(PrivateNote.live_set_id == s_id, PrivateNote.user_id == user_id)
        )).one()
        if not body.strip() or body.strip() == mine.body_md.strip():
            continue
        merged = f"{mine.body_md.rstrip()}\n\n{body}" if mine.body_md.strip() else body
        await session.execute(
            update(PrivateNote)
            .where(PrivateNote.live_set_id == s_id, PrivateNote.user_id == user_id)
            .values(body_md=merged, updated_at=max(updated_at, mine.updated_at))
            .execution_options(synchronize_session=False)
        )
        count += 1
    await session.execute(delete(PrivateNote).where(PrivateNote.live_set_id == l_id)
                          .execution_options(synchronize_session=False))
    return count


async def merge_pair(
    session: AsyncSession, *, survivor: LiveSet, loser: LiveSet,
    offset_seconds: float = 0.0, trigger: str = TRIGGER,
) -> SetUpgradeEvent:
    """Merge ``loser`` into ``survivor`` and recycle it (no audio change).

    ``offset_seconds``: where the loser's audio starts within the
    survivor's (``compare(survivor, loser).offset_seconds``). The caller
    chooses the survivor (spec §4.7: the higher tier, else the older set;
    a better newer copy is swapped into the older set first, see
    :func:`resolve_pair`). One commit; rolled back on any error.
    """
    if survivor.id == loser.id:
        raise ValueError("a merge needs two different sets")
    try:
        locked = await _lock_sets(session, survivor.id, loser.id)
        survivor, loser = locked.get(survivor.id), locked.get(loser.id)
        if survivor is None or loser is None:
            raise ValueError("survivor or loser no longer exists")
        if survivor.deleted_at is not None or loser.deleted_at is not None:
            raise ValueError("survivor or loser is in the recycle bin")
        # _merge_rows flips the loser to draft; remember what it was.
        loser_was_published = loser.status == "published"
        event = await _merge_rows(session, survivor=survivor, loser=loser,
                                  offset_seconds=offset_seconds, trigger=trigger)
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    await announce_recycled(loser, was_published=loser_was_published)
    return event


# --------------------------------------------------------------------------
# Batched cleanup (driven by jobs/quality_backfill.py)
# --------------------------------------------------------------------------

def _cursor_key(cursor: list | tuple | None) -> tuple[datetime, uuid.UUID] | None:
    if not cursor:
        return None
    return (datetime.fromisoformat(cursor[0]), uuid.UUID(cursor[1]))


async def run_cleanup_batch(
    *, cursor: list | None = None, deadline: float | None = None,
) -> dict:
    """Walk eligible sets oldest first, after ``cursor``, resolving each one
    that matches an older set. At least one set is checked per call; then it
    stops at ``deadline``. Returns ``{"merged", "skipped", "errors",
    "cursor", "done"}``; pass ``cursor`` back to continue. A crash just
    re-checks the sets after the last cursor handed back; resolved pairs
    drop out of the scan (the newer set is recycled or flagged)."""
    after = _cursor_key(cursor)
    counts = {"merged": 0, "skipped": 0, "errors": 0}
    first = True
    async with session_factory()() as read:
        cache = _RawCache(read)
        index = await _load_index(read)
        await read.rollback()  # don't sit idle in a transaction while comparing
        while True:
            i = next((n for n, e in enumerate(index) if after is None or e.key > after), None)
            if i is None:
                return {**counts, "cursor": _dump(after), "done": True}
            if not first and deadline is not None and time.monotonic() >= deadline:
                return {**counts, "cursor": _dump(after), "done": False}
            first = False
            pair = await _find_older(index, i, cache)
            await read.rollback()
            after = index[i].key
            if pair is None:
                continue
            try:
                outcome = await resolve_pair(pair)
            except Exception:
                logger.warning("duplicate cleanup failed for %s -> %s",
                               pair.newer_id, pair.older_id, exc_info=True)
                counts["errors"] += 1
                continue
            if outcome in counts:
                counts[outcome] += 1
            # The survivor may have new audio (and fingerprint); the newer
            # set dropped out. Re-read before checking the next set.
            index = await _load_index(read)
            await read.rollback()


def _dump(key: tuple[datetime, uuid.UUID] | None) -> list | None:
    return None if key is None else [key[0].isoformat(), str(key[1])]
