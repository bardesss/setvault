"""Swap a better copy's audio into an existing set (Phase 7D spec §4.6).

``apply_upgrade`` keeps the existing set's row (id, slug, metadata, comments,
tracklist, bookmarks, history) and swaps its audio with a processed arrival.
The arrival takes the old audio and goes to the recycle bin, so the purge job
removes the old files after the grace window and *Restore* brings the old copy
back as a separate draft set.

Crash safety: the swap is DB-only. Files live under paths unique to the set or
rip that created them (``originals/<id>/``, ``stream/<id>.opus``,
``waveform/<id>.json``), so exchanging the path strings between two rows in one
transaction moves the audio without moving a file. A failure anywhere before
the commit leaves both rows on their own, untouched files. Do not add file I/O
to ``apply_upgrade``; ``test_swap_does_no_file_io`` guards this.

``discard_arrival`` is the opposite outcome: the candidate was not the same
audio or not better, so its row and files go and the target records a
``rejected`` event so the candidate is not downloaded again.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_core.jobs.ready import fan_out_webhooks
from setvault_core.models.catalog import LiveSet, MediaRoot, SetFingerprint
from setvault_core.models.engagement import ListeningHistory, UserSetState
from setvault_core.models.engagement_3c import Bookmark, Comment
from setvault_core.models.tracklist import TracklistEntry
from setvault_core.models.upgrades import SetUpgradeEvent
from setvault_core.services.notifications import notify_set_upgraded

logger = logging.getLogger(__name__)

# Same grace window as a manual delete (sets.py delete_set).
RECYCLE_GRACE = timedelta(days=14)
# Offsets below this are alignment noise; positions are whole seconds anyway.
MIN_SHIFT_SECONDS = 1.0
_REPLACED_SUFFIX = " (replaced copy)"
_TITLE_MAX = 512  # LiveSet.title is String(512)

# The columns that describe the audio file itself. They move together: the
# path strings are relative to ``media_root_id``.
_AUDIO_FIELDS = (
    "media_root_id",
    "audio_path",
    "streaming_path",
    "waveform_path",
    "duration_seconds",
    "normalized_lufs",
    "audio_codec",
    "audio_bitrate_kbps",
    "audio_sample_rate",
    "audio_bit_depth",
    "audio_lossless",
    "quality_tier",
    "quality_measured_at",
    "source_type",
    "source_url",
    "source_external_id",
)

# (model, column, integer column?) for every time position on a set.
_POSITION_COLUMNS = (
    (TracklistEntry, TracklistEntry.start_seconds, True),
    (TracklistEntry, TracklistEntry.end_seconds, True),
    (Comment, Comment.position_seconds, True),
    (Bookmark, Bookmark.position_seconds, True),
    (UserSetState, UserSetState.position_seconds, False),
    (ListeningHistory, ListeningHistory.last_position_seconds, False),
)


def _event(
    target: LiveSet, candidate: LiveSet, *, outcome: str, trigger: str,
    reason: str | None, candidate_source_kind: str | None,
    candidate_external_id: str | None,
) -> SetUpgradeEvent:
    """History row: ``from`` is the target's current audio, ``to`` the candidate's."""
    return SetUpgradeEvent(
        live_set_id=target.id,
        trigger=trigger,
        outcome=outcome,
        reason=reason,
        from_tier=target.quality_tier,
        from_codec=target.audio_codec,
        from_bitrate_kbps=target.audio_bitrate_kbps,
        from_source_type=target.source_type,
        from_source_url=target.source_url,
        to_tier=candidate.quality_tier,
        to_codec=candidate.audio_codec,
        to_bitrate_kbps=candidate.audio_bitrate_kbps,
        to_source_type=candidate.source_type,
        to_source_url=candidate.source_url,
        candidate_source_kind=candidate_source_kind,
        candidate_external_id=candidate_external_id,
        offset_seconds=candidate.match_offset_seconds,
    )


async def _shift_positions(session: AsyncSession, live: LiveSet, offset: float) -> None:
    """Move every time position on ``live`` by ``-offset``, clamping at 0.

    ``offset > 0`` means the new copy starts later in the set, so existing
    time t is at t - offset in the new audio. NULL positions stay NULL (Postgres
    GREATEST ignores NULLs and would turn them into 0).
    """
    whole = round(offset)
    for model, col, is_int in _POSITION_COLUMNS:
        delta = whole if is_int else offset
        await session.execute(
            update(model)
            .where(model.live_set_id == live.id, col.is_not(None))
            .values({col.key: func.greatest(col - delta, 0)})
            .execution_options(synchronize_session="fetch")
        )


async def _swap_fingerprints(session: AsyncSession, a: LiveSet, b: LiveSet) -> None:
    a_ids = (await session.execute(
        select(SetFingerprint.id).where(SetFingerprint.live_set_id == a.id)
    )).scalars().all()
    b_ids = (await session.execute(
        select(SetFingerprint.id).where(SetFingerprint.live_set_id == b.id)
    )).scalars().all()
    for ids, new_owner in ((a_ids, b.id), (b_ids, a.id)):
        if ids:
            await session.execute(
                update(SetFingerprint)
                .where(SetFingerprint.id.in_(ids))
                .values(live_set_id=new_owner)
                .execution_options(synchronize_session="fetch")
            )


async def apply_upgrade(
    session: AsyncSession,
    *,
    target: LiveSet,
    arrival: LiveSet,
    trigger: str,
    candidate_source_kind: str | None = None,
    candidate_external_id: str | None = None,
) -> SetUpgradeEvent:
    """Give ``target`` the arrival's audio and recycle the old copy.

    Preconditions: the arrival is fully processed (stream and waveform exist)
    and the caller has checked the match and the tier. One commit; webhooks and
    the owner's notification go out after it. On a failure before the commit
    the transaction is rolled back and the error re-raised.
    """
    if arrival.id == target.id:
        raise ValueError("an upgrade needs two different sets")
    if not arrival.streaming_path or not arrival.waveform_path:
        raise ValueError("arrival is not fully processed (no stream or waveform)")
    if target.deleted_at is not None:
        raise ValueError("target set is in the recycle bin")

    try:
        event = _event(
            target, arrival, outcome="upgraded", trigger=trigger, reason=None,
            candidate_source_kind=candidate_source_kind,
            candidate_external_id=candidate_external_id,
        )
        offset = arrival.match_offset_seconds

        # No file I/O from here to the commit: only path strings change hands.
        old = {f: getattr(target, f) for f in _AUDIO_FIELDS}
        for f in _AUDIO_FIELDS:
            setattr(target, f, getattr(arrival, f))
            setattr(arrival, f, old[f])
        await _swap_fingerprints(session, target, arrival)
        if offset is not None and abs(offset) >= MIN_SHIFT_SECONDS:
            await _shift_positions(session, target, offset)

        now = datetime.now(UTC)
        base = target.title[: _TITLE_MAX - len(_REPLACED_SUFFIX)]
        arrival.title = f"{base}{_REPLACED_SUFFIX}"
        arrival.status = "draft"
        arrival.duplicate_of = None
        arrival.match_offset_seconds = None
        arrival.deleted_at = now
        arrival.purge_after_at = now + RECYCLE_GRACE

        session.add(event)
        await session.flush()
        await session.commit()
    except Exception:
        await session.rollback()
        raise

    logger.info("upgraded set %s from %s to %s", target.id, event.from_tier, event.to_tier)
    await fan_out_webhooks(target, "set.published")
    try:
        await notify_set_upgraded(session, target, event)
        await session.commit()
    except Exception:
        # The swap is committed; a missing bell entry must not undo it.
        logger.exception("set_upgraded notification failed for %s", target.id)
        await session.rollback()
    return event


def _unlink(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("discard: failed to unlink %s: %s", path, exc)


async def discard_arrival(
    session: AsyncSession,
    arrival: LiveSet,
    *,
    target: LiveSet | None,
    trigger: str,
    reason: str,
    candidate_source_kind: str | None = None,
    candidate_external_id: str | None = None,
) -> None:
    """Delete a candidate that is not an upgrade: its row, fingerprint and
    files. With a ``target``, records a ``rejected`` event on it so the
    candidate is not tried again.

    The row goes first (one commit, with the event); files are removed only
    after that, so a crash leaves orphan files rather than a row pointing at
    nothing. A file another set still references is kept.
    """
    if target is not None and target.id == arrival.id:
        raise ValueError("cannot discard the target itself")
    if arrival.status == "published":
        raise ValueError("refusing to discard a published set")

    root = await session.get(MediaRoot, arrival.media_root_id)
    rels = list(dict.fromkeys(r for r in (
        arrival.audio_path, arrival.streaming_path, arrival.waveform_path, arrival.thumb_path,
    ) if r))
    # Never delete a file some other set points at.
    to_delete: list[str] = []
    for rel in rels:
        shared = await session.scalar(
            select(func.count()).select_from(LiveSet).where(
                LiveSet.id != arrival.id,
                LiveSet.media_root_id == arrival.media_root_id,
                or_(LiveSet.audio_path == rel, LiveSet.streaming_path == rel,
                    LiveSet.waveform_path == rel, LiveSet.thumb_path == rel),
            )
        )
        if shared:
            logger.warning("discard: keeping %s, another set uses it", rel)
        else:
            to_delete.append(rel)

    arrival_id = arrival.id
    try:
        if target is not None:
            session.add(_event(
                target, arrival, outcome="rejected", trigger=trigger, reason=reason[:200],
                candidate_source_kind=candidate_source_kind,
                candidate_external_id=candidate_external_id,
            ))
        await session.delete(arrival)
        await session.flush()
        await session.commit()
    except Exception:
        await session.rollback()
        raise

    if root is None:
        return
    host = Path(root.host_path)
    parents: set[Path] = set()
    for rel in to_delete:
        _unlink(host / rel)
        parents.add((host / rel).parent)
    parents.add(host / "originals" / str(arrival_id))
    # Tidy the per-set/per-rip originals dir if it is now empty.
    for d in parents:
        if d.parent.name == "originals" and d.parent.parent == host:
            try:
                d.rmdir()
            except OSError:
                pass
