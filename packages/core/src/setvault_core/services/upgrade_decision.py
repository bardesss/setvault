"""What happens to an arrival at the end of ingest (Phase 7D spec §4.5 B, §4.6).

Every ingest path fingerprints its arrival, which flags ``duplicate_of`` when
the audio matches an existing set. The final pipeline stage then asks
:func:`decide_arrival`:

- **Upgrade-attempt rip** (the rip was downloaded for a target set): the
  arrival either upgrades the target or is discarded, never held, so a
  rejected candidate leaves no draft behind (only a ``rejected`` history row,
  which stops later sweeps from downloading it again).
- **Any other duplicate:** upgrades the matched set when it is strictly better
  and both switches allow it; otherwise it is held for the Duplicates page.
- **No match:** published as usual.

``apply_upgrade`` and ``discard_arrival`` lock rows and roll the session back
when they refuse, so everything read or flushed here is committed before
either is called.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from setvault_core.models.catalog import LiveSet
from setvault_core.services.quality_profile import QualityProfile, get_profile, is_better
from setvault_core.services.set_upgrade import apply_upgrade, discard_arrival
from setvault_core.services.system_config import get_config

logger = logging.getLogger(__name__)

Outcome = Literal["upgraded", "held", "discarded", "publish"]


@dataclass(frozen=True)
class Decision:
    outcome: Outcome
    reason: str | None = None
    # The set that was upgraded (``upgraded`` only), for messages.
    target_title: str | None = None


def _better(profile: QualityProfile, arrival: LiveSet, target: LiveSet) -> bool:
    return is_better(
        profile, arrival.quality_tier, target.quality_tier,
        candidate_lossless=arrival.audio_lossless, current_lossless=target.audio_lossless,
    )


async def _switches_on(session: AsyncSession, target: LiveSet) -> bool:
    if not target.upgrades_enabled:
        return False
    return bool((await get_config(session)).auto_upgrades_enabled)


async def upgrade_attempt_rejection(
    session: AsyncSession, arrival: LiveSet, target_id: uuid.UUID,
) -> tuple[LiveSet | None, str | None]:
    """For an upgrade-attempt arrival: ``(target, reason)`` where ``reason``
    says why it can't upgrade the target, or is None when it can."""
    target = await session.get(LiveSet, target_id, populate_existing=True)
    if target is None or target.deleted_at is not None:
        return target, "target unavailable"
    if not await _switches_on(session, target):
        return target, "upgrades off"
    if arrival.duplicate_of != target.id:
        return target, "different audio"
    if not _better(await get_profile(session), arrival, target):
        return target, "not better"
    return target, None


async def _discard(
    session: AsyncSession, arrival: LiveSet, target: LiveSet | None, *, reason: str,
    trigger: str, candidate_source_kind: str | None, candidate_external_id: str | None,
) -> bool:
    """Commit, then discard. False when ``discard_arrival`` refused."""
    await session.commit()
    try:
        await discard_arrival(
            session, arrival, target=target, trigger=trigger, reason=reason,
            candidate_source_kind=candidate_source_kind,
            candidate_external_id=candidate_external_id,
        )
    except ValueError:
        logger.warning("not discarding arrival %s (%s): refused", arrival.id, reason,
                       exc_info=True)
        return False
    logger.info("discarded upgrade candidate %s: %s", arrival.id, reason)
    return True


async def discard_unless_upgrade(
    session: AsyncSession, arrival: LiveSet, *, target_id: uuid.UUID, trigger: str,
    candidate_source_kind: str | None = None, candidate_external_id: str | None = None,
) -> str | None:
    """Discard an upgrade-attempt arrival that can't upgrade its target.
    Returns the reason when it was discarded, None when it may go on (it can
    upgrade, it is already recycled, or the discard was refused)."""
    if arrival.deleted_at is not None:
        return None
    target, reason = await upgrade_attempt_rejection(session, arrival, target_id)
    if reason is None:
        return None
    discarded = await _discard(
        session, arrival, target, reason=reason, trigger=trigger,
        candidate_source_kind=candidate_source_kind,
        candidate_external_id=candidate_external_id,
    )
    return reason if discarded else None


async def _upgrade(
    session: AsyncSession, arrival: LiveSet, target: LiveSet, *, trigger: str,
    candidate_source_kind: str | None, candidate_external_id: str | None,
) -> Decision:
    title = target.title
    await session.commit()
    try:
        await apply_upgrade(
            session, target=target, arrival=arrival, trigger=trigger,
            candidate_source_kind=candidate_source_kind,
            candidate_external_id=candidate_external_id,
        )
    except ValueError as exc:
        # UpgradeNoLongerApplicable (target or arrival changed underneath) or
        # an arrival without stream/waveform: keep it for the Duplicates page.
        logger.warning("upgrade of %s from %s not applied: %s", target.id, arrival.id, exc)
        return Decision("held", str(exc))
    return Decision("upgraded", target_title=title)


async def decide(
    session: AsyncSession, arrival: LiveSet, *, upgrade_target_id: uuid.UUID | None,
    trigger: str, candidate_source_kind: str | None = None,
    candidate_external_id: str | None = None,
) -> Decision:
    """:func:`decide_arrival` with the reason and target title attached."""
    if arrival.deleted_at is not None:
        # The fingerprint stage recycled it (same audio as a recycled
        # original, and not better): never upgrade from it, never publish it.
        return Decision("held", "arrival is in the recycle bin")

    candidate = {"candidate_source_kind": candidate_source_kind,
                 "candidate_external_id": candidate_external_id}
    if upgrade_target_id is not None:
        target, reason = await upgrade_attempt_rejection(session, arrival, upgrade_target_id)
        if reason is not None:
            if await _discard(session, arrival, target, reason=reason, trigger=trigger,
                              **candidate):
                return Decision("discarded", reason)
            return Decision("held", reason)
        return await _upgrade(session, arrival, target, trigger=trigger, **candidate)

    if arrival.duplicate_of is None:
        return Decision("publish")

    target = await session.get(LiveSet, arrival.duplicate_of, populate_existing=True)
    if (
        target is None
        or target.deleted_at is not None
        or not await _switches_on(session, target)
        or not _better(await get_profile(session), arrival, target)
    ):
        return Decision("held", "duplicate")
    return await _upgrade(session, arrival, target, trigger=trigger, **candidate)


async def decide_arrival(
    session: AsyncSession, arrival: LiveSet, *, upgrade_target_id: uuid.UUID | None,
    trigger: str, candidate_source_kind: str | None = None,
    candidate_external_id: str | None = None,
) -> Outcome:
    """Upgrade, hold, discard or publish ``arrival`` (see the module doc).
    Only ``publish`` leaves work for the caller: flipping the set to published.
    """
    decision = await decide(
        session, arrival, upgrade_target_id=upgrade_target_id, trigger=trigger,
        candidate_source_kind=candidate_source_kind,
        candidate_external_id=candidate_external_id,
    )
    return decision.outcome
