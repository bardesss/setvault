"""Find the original set an arrival duplicates (spec §4.2)."""
from __future__ import annotations

import array
import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_core.models.catalog import LiveSet, SetFingerprint
from setvault_core.services.audio_match import (
    MATCHER_VERSION,
    MatchResult,
    compare,
    is_same_audio,
    raw_from_bytes,
)

DURATION_TOLERANCE_PCT = 0.10
DURATION_TOLERANCE_SECONDS = 60.0


async def find_original_match(
    session: AsyncSession, live: LiveSet, raw: array.array, duration: float,
) -> tuple[LiveSet, MatchResult] | None:
    """The original set that ``raw`` is another copy of, with the match result.

    Candidates are other sets with a current-version raw fingerprint and a
    duration within ±10% or ±60 s (the larger). Only sets that are not
    themselves flagged duplicates can be the original; of those, the
    earliest-created live one wins, else the earliest soft-deleted one (the
    caller undeletes it, spec §A6). The result's offset is for
    ``compare(existing, arrival)``: > 0 means the arrival starts later.
    """
    tol = max(DURATION_TOLERANCE_PCT * duration, DURATION_TOLERANCE_SECONDS)
    rows = (await session.execute(
        select(LiveSet, SetFingerprint)
        .join(SetFingerprint, SetFingerprint.live_set_id == LiveSet.id)
        .where(
            LiveSet.id != live.id,
            LiveSet.duplicate_of.is_(None),
            SetFingerprint.raw.is_not(None),
            SetFingerprint.raw_version == MATCHER_VERSION,
            SetFingerprint.duration_seconds.between(duration - tol, duration + tol),
        )
        # Live sets first, then oldest; one set can hold several rows.
        .order_by(LiveSet.deleted_at.is_not(None), LiveSet.created_at, LiveSet.id,
                  SetFingerprint.created_at),
    )).all()

    seen: set = set()
    for candidate, fp in rows:
        if candidate.id in seen:
            continue
        # compare() is CPU-bound pure Python; keep the event loop free.
        result = await asyncio.to_thread(compare, raw_from_bytes(fp.raw), raw)
        if is_same_audio(result):
            return candidate, result
        seen.add(candidate.id)
    return None
