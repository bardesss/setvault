"""Soundboard-keyword hint — a tie-breaker between candidates of equal tier."""
from __future__ import annotations

import re

_PATTERN = re.compile(
    r"(?<![a-z0-9])(?:sbd|soundboard|pre-?fm|desk[\s-]+recording|line[\s-]?in)(?![a-z0-9])",
    re.IGNORECASE,
)


def has_soundboard_hint(text: str | None) -> bool:
    return bool(text and _PATTERN.search(text))


def strip_soundboard_terms(text: str | None) -> str:
    """``text`` with the soundboard keywords blanked out, so two titles that
    differ only by "(SBD)" compare as the same set."""
    return _PATTERN.sub(" ", text or "")
