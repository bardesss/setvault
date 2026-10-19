"""What happens to an arrival at the end of ingest (Phase 7D spec §4.5 B, §4.6).

Every ingest path fingerprints its arrival, which flags ``duplicate_of`` when
the audio matches an existing set (an upgrade-attempt rip is compared with its
target only, R28). The final pipeline stage then asks
:func:`decide_arrival`:

- **Upgrade-attempt rip** (the rip was downloaded for a target set): the
  arrival either upgrades the target or is discarded, so a rejected candidate
  leaves no draft behind (only a ``rejected`` history row, which stops later
  sweeps from downloading it again).
- **Any other duplicate:** upgrades the matched set when it is strictly better,
  both switches allow it and the uploader owns the set (or is an admin);
  otherwise it is held for the Duplicates page.
- **No match:** published as usual.

``apply_upgrade`` repeats the switch/owner/quality checks under its row locks,
so a decision made here on an unlocked read can't swap in a copy that a
parallel arrival has already beaten.

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
from setvault_core.services.set_upgrade import (
    apply_upgrade,
    discard_arrival,
    upgrade_refusal,
    upgrade_switches_on,
)

logger = logging.getLogger(__name__)

Outcome = Literal["upgraded", "held", "discarded", "publish"]

_RECYCLED = "arrival is in the recycle bin"


@dataclass(frozen=True)
class Decision:
    outcome: Outcome
    reason: str | None = None
    # The set that was upgraded (``upgraded`` only), for messages.
    target_title: str | None = None

    @property
    def message(self) -> str:
        """The line shown in progress events and the rip's Jobs entry."""
        if self.outcome == "publish":
            return "published"
        if self.outcome == "upgraded":
            return f'upgraded "{self.target_title}" to a better copy'
        if self.outcome == "discarded":
            return f"no upgrade: {self.reason}"
        if self.reason == "duplicate":
            return "held for review: duplicate"
        return f"held: {self.reason}"


async def upgrade_attempt_rejection(
    session: AsyncSession, arrival: LiveSet, target_id: uuid.UUID, *, trigger: str,
) -> tuple[LiveSet | None, str | None]:
    """For an upgrade-attempt arrival: ``(target, reason)`` where ``reason``
    says why it can't upgrade the target, or is None when it can. The arrival's
    uploader is the rip's submitter, so the ownership rule applies too."""
    target = await session.get(LiveSet, target_id, populate_existing=True)
    if target is None or target.deleted_at is not None:
        return target, "target unavailable"
    if not await upgrade_switches_on(session, target, trigger=trigger):
        return target, "upgrades off"
    if arrival.duplicate_of != target.id:
        return target, "different audio"
    return target, await upgrade_refusal(session, arrival, target, trigger=trigger)


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
) -> Decision | None:
    """Early check for an upgrade-attempt arrival, before the expensive
    stages. Returns a final decision (``discarded``, or ``held`` when the
    fingerprint stage already recycled it), or None when the pipeline should
    go on (it can upgrade, or the discard was refused)."""
    if arrival.deleted_at is not None:
        return Decision("held", _RECYCLED)
    target, reason = await upgrade_attempt_rejection(
        session, arrival, target_id, trigger=trigger,
    )
    if reason is None:
        return None
    discarded = await _discard(
        session, arrival, target, reason=reason, trigger=trigger,
        candidate_source_kind=candidate_source_kind,
        candidate_external_id=candidate_external_id,
    )
    return Decision("discarded", reason) if discarded else None


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
        # UpgradeNoLongerApplicable (the locked re-check failed: target or
        # arrival changed underneath) or an arrival without stream/waveform:
        # it stays a draft duplicate for the Duplicates page.
        logger.warning("upgrade of %s from %s not applied: %s", target.id, arrival.id, exc)
        return Decision("held", "duplicate")
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
        return Decision("held", _RECYCLED)

    candidate = {"candidate_source_kind": candidate_source_kind,
                 "candidate_external_id": candidate_external_id}
    if upgrade_target_id is not None:
        target, reason = await upgrade_attempt_rejection(
            session, arrival, upgrade_target_id, trigger=trigger,
        )
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
        or await upgrade_refusal(session, arrival, target, trigger=trigger) is not None
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
