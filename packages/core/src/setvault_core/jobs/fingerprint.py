from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from setvault_core.db import init_engine, run_job, session_factory
from setvault_core.models.catalog import LiveSet, MediaRoot, SetFingerprint
from setvault_core.progress import ProgressEvent, publish
from setvault_core.services.audio_match import (
    MATCHER_VERSION,
    compute_raw_fingerprint,
    raw_to_bytes,
)
from setvault_core.services.audit import log as audit_log
from setvault_core.services.quality_profile import get_profile, is_better
from setvault_core.services.set_match import find_original_match

logger = logging.getLogger(__name__)


async def store_fingerprint(
    s, live_set_id: uuid.UUID, raw_bytes: bytes, digest: str, duration: float,
) -> None:
    """Create or update the set's single SetFingerprint row (never a second)."""
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


async def fingerprint_audio(live_set_id: str) -> None:
    if "DATABASE_URL" in os.environ:
        init_engine(os.environ["DATABASE_URL"])

    async with session_factory()() as s:
        live = await s.get(LiveSet, uuid.UUID(live_set_id))
        if live is None:
            raise RuntimeError(f"LiveSet {live_set_id} missing")
        root = await s.get(MediaRoot, live.media_root_id)
        if root is None:
            raise RuntimeError("MediaRoot vanished")
        path = Path(root.host_path) / live.audio_path

        publish(ProgressEvent(
            kind="fingerprint", live_set_id=live_set_id, job_id=live_set_id,
            progress_pct=20, message="fingerprinting",
        ))

        # compute_raw_fingerprint tolerates chromaprint's exit-3-at-EOF quirk.
        raw, duration = await asyncio.to_thread(compute_raw_fingerprint, path)
        raw_bytes = raw_to_bytes(raw)
        digest = hashlib.sha256(raw_bytes).hexdigest()

        await store_fingerprint(s, live.id, raw_bytes, digest, duration)

        match = None
        if live.duplicate_of is None:
            match = await find_original_match(s, live, raw, duration)
        if match is not None:
            existing_live, result = match
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

        publish(ProgressEvent(
            kind="fingerprint", live_set_id=live_set_id, job_id=live_set_id,
            progress_pct=30,
            message=(
                "duplicate of existing set" if live.duplicate_of
                else "unique fingerprint"
            ),
        ))


def fingerprint_audio_sync(live_set_id: str) -> None:
    run_job(fingerprint_audio(live_set_id))
