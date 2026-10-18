from __future__ import annotations

from setvault_core.services.audio_quality import TIERS
from setvault_core.services.quality_profile import (
    QualityProfile,
    cutoff_unmet,
    get_profile,
    is_better,
    rank,
)

DEFAULT = QualityProfile(order=TIERS, cutoff="lossless")


def _better(p, candidate, current) -> bool:
    """is_better on tiers alone (container flags not measured)."""
    return is_better(p, candidate, current, candidate_lossless=None, current_lossless=None)


def test_is_better_is_strict():
    assert _better(DEFAULT, "high", "high") is False
    assert _better(DEFAULT, "lossless", "high") is True
    assert _better(DEFAULT, "low", "high") is False
    assert _better(DEFAULT, None, "low") is False
    assert _better(DEFAULT, "high", None) is False


def test_cutoff_unmet_default_profile():
    assert cutoff_unmet(DEFAULT, "high") is True
    assert cutoff_unmet(DEFAULT, "lossless") is False
    assert cutoff_unmet(DEFAULT, None) is False


def test_reordered_profile_changes_rank():
    p = QualityProfile(order=("high", "lossless", "good", "ok", "low"), cutoff="high")
    assert rank(p, "high") == 0
    assert rank(p, "lossless") == 1
    assert rank(p, None) > rank(p, "low")
    assert _better(p, "high", "lossless") is True
    assert _better(p, "lossless", "high") is False
    assert cutoff_unmet(p, "lossless") is True
    assert cutoff_unmet(p, "high") is False


def test_lossy_never_beats_lossless_container():
    assert is_better(
        DEFAULT, "high", "ok", candidate_lossless=False, current_lossless=True,
    ) is False
    assert is_better(
        DEFAULT, "high", "ok", candidate_lossless=None, current_lossless=True,
    ) is False
    assert is_better(
        DEFAULT, "high", "ok", candidate_lossless=True, current_lossless=True,
    ) is True


async def test_get_profile_defaults(session):
    p = await get_profile(session)
    assert p.order == TIERS
    assert p.cutoff == "lossless"


def test_lossless_flags_are_required():
    import pytest

    with pytest.raises(TypeError):
        is_better(DEFAULT, "lossless", "high")  # type: ignore[call-arg]
