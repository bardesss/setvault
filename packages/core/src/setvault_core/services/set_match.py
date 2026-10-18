"""Find the original set an arrival duplicates (spec §4.2)."""
from __future__ import annotations

import array
import asyncio
import logging

from sqlalchemy import and_, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_core.models.catalog import LiveSet, SetFingerprint
from setvault_core.services.audio_match import (
    MATCHER_VERSION,
    MatchResult,
    compare,
    is_same_audio,
    raw_from_bytes,
)

logger = logging.getLogger(__name__)

DURATION_TOLERANCE_PCT = 0.10
DURATION_TOLERANCE_SECONDS = 60.0
# Upper bound on fuzzy compares per arrival (each is a few hundred ms of CPU).
MAX_COMPARES = 200
# The pre-7D exact rule for rows that only have the legacy hash.
LEGACY_DURATION_SECONDS = 2.0
LEGACY_EXACT_MATCH = MatchResult(
    similarity=1.0, offset_seconds=0.0, overlap=1.0, worst_window_ber=0.0,
)


async def find_original_match(
    session: AsyncSession, live: LiveSet, raw: array.array, duration: float,
    *, legacy_hash: str | None = None,
) -> tuple[LiveSet, MatchResult] | None:
    """The original set that ``raw`` is another copy of, with the match result.

    Candidates are other sets with a current-version raw fingerprint and a
    duration within ±10% or ±60 s (the larger). Separately, the old exact rule
    (same ``legacy_hash``, duration within ±2 s) matches any row, raw or not;
    it is the only match for clips too short for the fuzzy comparison, and
    exact hits don't count toward the compare cap. Only sets that are not
    themselves flagged duplicates can be the original; of those, the
    earliest-created live one wins, else the earliest soft-deleted one (the
    caller undeletes it, spec §A6). The result's offset is for
    ``compare(existing, arrival)``: > 0 means the arrival starts later.
    """
    tol = max(DURATION_TOLERANCE_PCT * duration, DURATION_TOLERANCE_SECONDS)
    comparable = and_(
        SetFingerprint.raw.is_not(None),
        SetFingerprint.raw_version == MATCHER_VERSION,
    )
    fuzzy = and_(
        comparable,
        SetFingerprint.duration_seconds.between(duration - tol, duration + tol),
    )
    exact = None
    where = fuzzy
    if legacy_hash is not None:
        # Exact legacy digest + duration: counts for any row, raw or not. Short
        # clips (< ~15 s) are too short for the fuzzy matcher, so this is the
        # only way identical short files match.
        exact = and_(
            SetFingerprint.fingerprint_hash == legacy_hash,
            func.abs(SetFingerprint.duration_seconds - duration) < LEGACY_DURATION_SECONDS,
        )
        where = or_(fuzzy, exact)
    is_exact = exact if exact is not None else literal(False)
    # Ids only: raw blobs (a few hundred KB each) are fetched one at a time.
    rows = (await session.execute(
        select(LiveSet.id, SetFingerprint.id, comparable, is_exact)
        .join(SetFingerprint, SetFingerprint.live_set_id == LiveSet.id)
        .where(LiveSet.id != live.id, LiveSet.duplicate_of.is_(None), where)
        # Live sets first, then oldest; one set can hold several rows.
        .order_by(LiveSet.deleted_at.is_not(None), LiveSet.created_at, LiveSet.id,
                  SetFingerprint.created_at),
    )).all()

    seen: set = set()
    compares = 0
    capped = False
    for live_set_id, fp_id, is_comparable, exact_hit in rows:
        if exact_hit:
            return await session.get(LiveSet, live_set_id), LEGACY_EXACT_MATCH
        if live_set_id in seen or not is_comparable:
            continue
        if compares >= MAX_COMPARES:
            if not capped:
                capped = True
                logger.warning(
                    "match for %s: stopped after %d candidates (cap), %d left unchecked",
                    live.id, compares, len({r[0] for r in rows} - seen),
                )
            continue  # keep scanning: a later exact-digest hit still counts
        fp_raw = (await session.execute(
            select(SetFingerprint.raw).where(SetFingerprint.id == fp_id),
        )).scalar_one()
        compares += 1
        # compare() is CPU-bound pure Python; keep the event loop free.
        result = await asyncio.to_thread(compare, raw_from_bytes(fp_raw), raw)
        if is_same_audio(result):
            return await session.get(LiveSet, live_set_id), result
        seen.add(live_set_id)
    return None
