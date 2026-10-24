"""Static loudness gain applied when the Opus stream is transcoded (P2a A3).

The original file is never touched: the gain lives in the stream file, and
``LiveSet.stream_gain_db`` records which gain the current stream carries.
"""
from __future__ import annotations

# ebur128's floor. The old parser stored it for every set, and a silent set
# measures it too; either way it is no basis for a gain.
BOGUS_LUFS = -70.0

MIN_GAIN_DB = -20.0
MAX_GAIN_DB = 10.0
# -1 dBTP as a linear amplitude. ``level=false`` keeps alimiter from
# auto-levelling the output back up after limiting.
_LIMITER = "alimiter=limit=0.891:level=false"


def gain_for(measured_lufs: float | None, target_lufs: float | None) -> float:
    """Gain in dB that brings ``measured_lufs`` to ``target_lufs``, clamped to
    [-20, +10] and rounded to 0.1 dB. 0.0 when either is unknown, the target
    is off (None) or the measurement is the bogus ``-70.0``."""
    if measured_lufs is None or target_lufs is None or measured_lufs == BOGUS_LUFS:
        return 0.0
    gain = min(MAX_GAIN_DB, max(MIN_GAIN_DB, target_lufs - measured_lufs))
    # ``+ 0.0`` turns a rounded -0.0 into 0.0.
    return round(gain, 1) + 0.0


def audio_filter(gain_db: float) -> str | None:
    """ffmpeg ``-af`` value for ``gain_db``, or None when no filter is needed.
    A boost gets a true-peak limiter so it can't clip."""
    if gain_db == 0.0:
        return None
    volume = f"volume={gain_db:.1f}dB"
    return f"{volume},{_LIMITER}" if gain_db > 0 else volume
