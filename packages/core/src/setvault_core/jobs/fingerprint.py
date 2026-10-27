from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from setvault_core.db import init_engine, session_factory
from setvault_core.models.catalog import LiveSet, MediaRoot, SetFingerprint
from setvault_core.progress import ProgressEvent, publish
from setvault_core.services.audio_match import (
    MATCHER_VERSION,
    compute_legacy_digest,
    compute_raw_fingerprint,
    raw_to_bytes,
)
from setvault_core.services.audit import log as audit_log
from setvault_core.services.quality_profile import get_profile, is_better
from setvault_core.services.set_match import find_original_match, match_upgrade_target
from setvault_core.services.webhook_events import announce_recycled, announce_restored

logger = logging.getLogger(__name__)


async def store_fingerprint(
    s, live_set_id: uuid.UUID, raw_bytes: bytes, digest: str, duration: float,
) -> None:
    """Create or update the set's single SetFingerprint row (never a second).

    ``digest`` is the legacy exact-match hash (audio_match.compute_legacy_digest).
    """
    own = (await s.execute(
        select(SetFingerprint).where(SetFingerprint.live_set_id == live_set_id),
    )).scalars().first()
    if own is None:
        s.add(SetFingerprint(
            live_set_id=live_set_id, fingerprint_hash=digest, duration_seconds=duration,
            raw=raw_bytes, raw_version=MATCHER_VERSION,
        ))
    else:
        own.fingerprint_hash = digest
        own.duration_seconds = duration
        own.raw = raw_bytes
        own.raw_version = MATCHER_VERSION


async def _not_known_worse(s, arrival: LiveSet, original: LiveSet) -> bool:
    """True unless the arrival is measured and no better than the original.

    Probe runs before fingerprint, so both tiers are normally known; an
    unmeasured side counts as "not known to be worse" and keeps the arrival.
    """
    if arrival.quality_tier is None or original.quality_tier is None:
        return True
    return is_better(
        await get_profile(s), arrival.quality_tier, original.quality_tier,
        candidate_lossless=arrival.audio_lossless,
        current_lossless=original.audio_lossless,
    )


async def fingerprint_audio(
    live_set_id: str, *, upgrade_target_id: uuid.UUID | None = None,
) -> None:
    """Fingerprint the set's audio and flag ``duplicate_of`` on a match.

    ``upgrade_target_id`` (an upgrade-attempt rip, R28): the arrival is
    compared with that set only. It never points at, or restores, any other
    set; a match flags ``duplicate_of = target`` for the upgrade decision.
    """
    if "DATABASE_URL" in os.environ:
        init_engine(os.environ["DATABASE_URL"])
    sid = uuid.UUID(live_set_id)

    # Short sessions only (like the quality backfill): read, let the
    # connection go for the whole-file fpcalc runs and the compares, then
    # write in a fresh session.
    async with session_factory()() as s:
        live = await s.get(LiveSet, sid)
        if live is None:
            raise RuntimeError(f"LiveSet {live_set_id} missing")
        root = await s.get(MediaRoot, live.media_root_id)
        if root is None:
            raise RuntimeError("MediaRoot vanished")
        path = Path(root.host_path) / live.audio_path
        already_duplicate = live.duplicate_of is not None

    publish(ProgressEvent(
        kind="fingerprint", live_set_id=live_set_id, job_id=live_set_id,
        progress_pct=20, message="fingerprinting",
    ))

    # compute_raw_fingerprint tolerates chromaprint's exit-3-at-EOF quirk.
    raw, duration = await asyncio.to_thread(compute_raw_fingerprint, path)
    raw_bytes = raw_to_bytes(raw)
    digest = await asyncio.to_thread(compute_legacy_digest, path)

    # Match (reads only): the matcher releases its connection around each
    # compare. Only the matched set's id and the result leave this session.
    match_id: uuid.UUID | None = None
    result = None
    async with session_factory()() as s:
        if upgrade_target_id is not None:
            match = await match_upgrade_target(
                s, upgrade_target_id, raw, duration,
                legacy_hash=digest, release_connection=True,
            )
        elif not already_duplicate:
            match = await find_original_match(
                s, live, raw, duration, legacy_hash=digest, release_connection=True,
            )
        else:
            match = None
        if match is not None:
            match_id, result = match[0].id, match[1]

    async with session_factory()() as s:
        live = await s.get(LiveSet, sid)
        if live is None:
            raise RuntimeError(f"LiveSet {live_set_id} missing")
        await store_fingerprint(s, live.id, raw_bytes, digest, duration)
        matched = await s.get(LiveSet, match_id) if match_id is not None else None
        restored: LiveSet | None = None
        recycled: LiveSet | None = None

        if upgrade_target_id is not None:
            await _flag_upgrade_target_match(s, live, matched, result, duration)
            await s.commit()
            _publish_done(live)
            return

        if matched is not None and live.duplicate_of is None:
            existing_live = matched
            audit_after = {
                "duplicate_of": str(existing_live.id),
                "duration_seconds": duration,
                "similarity": result.similarity,
                "offset_seconds": result.offset_seconds,
            }
            if (existing_live.deleted_at is not None
                    and await _not_known_worse(s, live, existing_live)):
                # The original is in the recycle bin but this arrival may be
                # the better copy: keep it as a normal new set and leave the
                # recycled one where it is (never lose a better copy).
                audit_action = "ingest.recycled_original_kept_arrival"
                # The arrival is not flagged a duplicate, so don't say so.
                audit_after["recycled_original"] = audit_after.pop("duplicate_of")
            else:
                live.duplicate_of = existing_live.id
                live.match_offset_seconds = result.offset_seconds
                live.status = "draft"
                if existing_live.deleted_at is not None:
                    # Spec §A6: "if the existing set is soft-deleted in the
                    # recycle bin, undelete the existing set and discard the
                    # new one." The arrival is no better, so it goes to the
                    # recycle bin with the normal grace period (sets.py
                    # delete_set) and the purge job (5B.5) cleans it up.
                    existing_live.deleted_at = None
                    existing_live.purge_after_at = None
                    restored, recycled = existing_live, live
                    now = datetime.now(UTC)
                    live.deleted_at = now
                    live.purge_after_at = now + timedelta(days=14)
                    audit_action = "ingest.duplicate_of_recycled"
                else:
                    audit_action = "ingest.duplicate_detected"
            await audit_log(
                s,
                actor_user_id=existing_live.uploaded_by,
                actor_kind="system",
                action=audit_action,
                target_type="LiveSet",
                target_id=str(live.id),
                after=audit_after,
            )
        await s.commit()
        _publish_done(live)
        if restored is not None:
            await announce_restored(restored)
        if recycled is not None:
            await announce_recycled(recycled)


def _publish_done(live: LiveSet) -> None:
    publish(ProgressEvent(
        kind="fingerprint", live_set_id=str(live.id), job_id=str(live.id),
        progress_pct=30,
        message=(
            "duplicate of existing set" if live.duplicate_of
            else "unique fingerprint"
        ),
    ))


async def _flag_upgrade_target_match(
    s, live: LiveSet, target: LiveSet | None, result, duration: float,
) -> None:
    if target is None:
        live.duplicate_of = None
        live.match_offset_seconds = None
        return
    live.duplicate_of = target.id
    live.match_offset_seconds = result.offset_seconds
    await audit_log(
        s,
        actor_user_id=target.uploaded_by,
        actor_kind="system",
        action="ingest.upgrade_candidate_matched",
        target_type="LiveSet",
        target_id=str(live.id),
        after={
            "duplicate_of": str(target.id),
            "duration_seconds": duration,
            "similarity": result.similarity,
            "offset_seconds": result.offset_seconds,
        },
    )
