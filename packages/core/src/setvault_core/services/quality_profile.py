"""Library-wide quality profile: tier order + cutoff, stored on SystemConfig."""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from setvault_core.services.system_config import get_config


@dataclass(frozen=True)
class QualityProfile:
    order: tuple[str, ...]  # best first
    cutoff: str


async def get_profile(session: AsyncSession) -> QualityProfile:
    cfg = await get_config(session)
    return QualityProfile(
        order=tuple(cfg.quality_tiers_order), cutoff=cfg.quality_cutoff,
    )


def rank(profile: QualityProfile, tier: str | None) -> int:
    """0 is best. ``None`` (unmeasured) and unknown tiers rank worst."""
    if tier is None or tier not in profile.order:
        return len(profile.order)
    return profile.order.index(tier)


def is_better(
    profile: QualityProfile,
    candidate_tier: str | None,
    current_tier: str | None,
    *,
    candidate_lossless: bool | None,
    current_lossless: bool | None,
) -> bool:
    """Strictly better only. A lossy container never replaces a lossless one,
    since the fake-lossless heuristic can misrate a genuine FLAC. The
    lossless flags are required so no caller can forget them; pass ``None``
    when a side was not measured."""
    if candidate_tier is None or current_tier is None:
        return False
    if current_lossless is True and candidate_lossless is not True:
        return False
    return rank(profile, candidate_tier) < rank(profile, current_tier)


def effective_cutoff(profile: QualityProfile) -> str:
    """The cutoff tier to apply. A stored cutoff that isn't in the order
    (stale or hand-edited config) is treated as the best tier rather than
    the worst, so cutoff checks keep working."""
    if profile.cutoff in profile.order or not profile.order:
        return profile.cutoff
    return profile.order[0]


def cutoff_unmet(profile: QualityProfile, tier: str | None) -> bool:
    """True when a measured set sits below the (effective) cutoff tier."""
    if tier is None:
        return False
    return rank(profile, tier) > rank(profile, effective_cutoff(profile))
