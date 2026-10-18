"""Measure a set's audio quality (codec, bitrate, depth) and rate it with a tier."""
from __future__ import annotations

import json
import logging
import re
import subprocess
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from setvault_core.models.catalog import LiveSet

logger = logging.getLogger(__name__)

TIERS: tuple[str, ...] = ("lossless", "high", "good", "ok", "low")

# ffprobe codec names. DSD comes as dsd_lsbf, dsd_msbf and their _planar forms.
_LOSSLESS_CODECS = {
    "flac", "alac", "wavpack", "ape", "tta", "tak", "truehd", "mlp",
    "wmalossless", "shorten", "mp4als",
}
_LOSSLESS_PREFIXES = ("pcm_", "dsd_")
_HIGH_MP3_KBPS = 320
_HIGH_OTHER_KBPS = 256
_HIGH_OTHER_CODECS = {"aac", "opus", "vorbis"}

# Fake-lossless check: a lossy encoder low-passes with a brick-wall cutoff
# (128k MP3 near 17-19 kHz, 192k+ near 19-20 kHz). Genuine audio rolls off
# gradually, however tilted its spectrum is, so we look for a *cliff* between
# a band just below a cutoff and a band just above it. To stay conservative a
# band only counts as cut when BOTH the cliff is large AND the band above it is
# nearly empty in absolute terms, so genuine lossless is never downgraded on
# a borderline reading.
_WINDOW_SECONDS = 30
_WINDOW_POSITIONS = (0.10, 0.50, 0.90)
# (below, above) bands in Hz for the 128k-style and the 192k-style cutoff.
_BANDS_16K = ((14000, 16000), (17000, 18500))
_BANDS_19K = ((17500, 19000), (19500, 21000))
_MIN_SAMPLE_RATE = 44100  # the 19.5-21 kHz band needs a Nyquist above 21 kHz
# Each band edge is a chain of 2-pole filters; fewer stages leak far too much.
_FILTER_STAGES = 8
# volumedetect works in 16-bit and cannot see below about -91 dBFS, and the
# narrow 8-stage bands attenuate noise by ~25 dB, so lift the signal before
# measuring and subtract the lift again.
_GAIN_DB = 40.0
# Cliff = below-band minus above-band level, in dB.
# Measured (dB; 16k pair cliff / 19k pair cliff): white->128k->FLAC 15.8 / 43;
# white->192k->FLAC 0.2 / 35; genuine white 0 / -8.7; pink 0.7 / -11.4; brown
# 0.8 / -11.8; white 48 kHz 1.8 / -4.6; pink lowpassed at 3 kHz 10 / -1.2 (floor);
# pink lowpassed at 15 kHz + white hiss 7.2 / 0.4.
_CLIFF_DB_16K = 12.0
_CLIFF_DB_19K = 15.0
# Absolute level (dBFS) the band above the cutoff must be below. Measured upper
# bands: 128k fake -69.1 (17-18.5 kHz), -96.7 (19.5-21 kHz); 192k fake -87.7
# (19.5-21 kHz); genuine hiss/steep roll-offs read -80 to -96 here, i.e. hiss
# at about -60 dBFS is below what this method can resolve in a narrow band, so
# this guard protects loud natural roll-offs (upper band above -65 dBFS) but
# cannot tell very quiet hiss from a lossy cut.
_UPPER_SILENT_DB = -65.0
_FLOOR_DB = -120.0  # band so quiet volumedetect reports nothing
_FFMPEG_TIMEOUT = 120  # seconds per 30 s window decode
# All window decodes of one file together (12 of them); past this the check
# gives up and the file keeps its "lossless" rating.
QUALITY_CHECK_BUDGET_SECONDS = 180
_FFPROBE_TIMEOUT = 60

_MEAN_RE = re.compile(r"mean_volume:\s*(-?[\d.]+|-inf)\s*dB")


@dataclass(frozen=True)
class AudioQuality:
    codec: str
    bitrate_kbps: int | None
    sample_rate: int | None
    bit_depth: int | None
    lossless: bool
    tier: str


def apply_quality(live: LiveSet, q: AudioQuality) -> None:
    """Copy a measured ``AudioQuality`` onto the LiveSet's quality columns."""
    live.audio_codec = q.codec[:32]
    live.audio_bitrate_kbps = q.bitrate_kbps
    live.audio_sample_rate = q.sample_rate
    live.audio_bit_depth = q.bit_depth
    live.audio_lossless = q.lossless
    live.quality_tier = q.tier
    live.quality_measured_at = datetime.now(UTC)


def is_lossless_codec(codec: str) -> bool:
    return codec in _LOSSLESS_CODECS or codec.startswith(_LOSSLESS_PREFIXES)


def tier_for(codec: str, bitrate_kbps: int | None, lossless: bool) -> str:
    if lossless:
        return "lossless"
    if bitrate_kbps is None:
        return "ok"
    if codec == "mp3" and bitrate_kbps >= _HIGH_MP3_KBPS:
        return "high"
    if codec in _HIGH_OTHER_CODECS and bitrate_kbps >= _HIGH_OTHER_KBPS:
        return "high"
    if bitrate_kbps >= 192:
        return "good"
    if bitrate_kbps >= 128:
        return "ok"
    return "low"


def _int_or_none(v: object) -> int | None:
    try:
        n = int(float(str(v)))
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def _band_volume(path: Path, start: float, band: tuple[int, int],
                 deadline: float) -> float:
    lo, hi = band
    stage = f"highpass=f={lo},lowpass=f={hi}"
    af = ",".join([stage] * _FILTER_STAGES) + f",volume={_GAIN_DB:g}dB,volumedetect"
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-ss", f"{start:.2f}",
           "-t", str(_WINDOW_SECONDS), "-i", str(path), "-vn", "-af", af,
           "-f", "null", "-"]
    left = deadline - time.monotonic()
    if left <= 0:
        raise subprocess.TimeoutExpired(cmd, QUALITY_CHECK_BUDGET_SECONDS)
    res = subprocess.run(  # noqa: S603
        cmd, capture_output=True, text=True, check=True,
        timeout=min(_FFMPEG_TIMEOUT, left))
    m = _MEAN_RE.search(res.stderr)
    if not m or m.group(1) == "-inf":
        return _FLOOR_DB
    return float(m.group(1)) - _GAIN_DB


def _is_cut(path: Path, starts: list[float], bands: tuple[tuple[int, int], ...],
            cliff_db: float, deadline: float) -> bool:
    below, above = bands
    lows = [_band_volume(path, t, below, deadline) for t in starts]
    highs = [_band_volume(path, t, above, deadline) for t in starts]
    cliff = sum(lo - hi for lo, hi in zip(lows, highs, strict=True)) / len(starts)
    return cliff > cliff_db and sum(highs) / len(highs) < _UPPER_SILENT_DB


def _fake_lossless_tier(path: Path, duration: float) -> str:
    """Rate a lossless file by looking for a lossy low-pass cliff: lossless, good or ok."""
    last_start = max(0.0, duration - _WINDOW_SECONDS)
    starts = [min(max(0.0, duration * pos - _WINDOW_SECONDS / 2), last_start)
              for pos in _WINDOW_POSITIONS]
    deadline = time.monotonic() + QUALITY_CHECK_BUDGET_SECONDS
    if _is_cut(path, starts, _BANDS_16K, _CLIFF_DB_16K, deadline):
        return "ok"
    if _is_cut(path, starts, _BANDS_19K, _CLIFF_DB_19K, deadline):
        return "good"
    return "lossless"


def measure_quality(path: Path) -> AudioQuality:
    cmd = ["ffprobe", "-v", "error", "-show_streams", "-show_format",
           "-of", "json", str(path)]
    out = subprocess.run(  # noqa: S603
        cmd, capture_output=True, text=True, check=True, timeout=_FFPROBE_TIMEOUT)
    info = json.loads(out.stdout)
    streams = [s for s in info.get("streams", []) if s.get("codec_type") == "audio"]
    if not streams:
        raise ValueError(f"no audio stream in {path}")
    st = streams[0]
    fmt = info.get("format", {})
    codec = str(st.get("codec_name", "unknown")).lower()
    bps = _int_or_none(st.get("bit_rate")) or _int_or_none(fmt.get("bit_rate"))
    kbps = round(bps / 1000) if bps else None
    depth = _int_or_none(st.get("bits_per_raw_sample")) or _int_or_none(
        st.get("bits_per_sample")
    )
    lossless = is_lossless_codec(codec)
    if lossless:
        duration = float(fmt.get("duration") or st.get("duration") or 0)
        rate = _int_or_none(st.get("sample_rate")) or 0
        try:
            tier = (_fake_lossless_tier(path, duration)
                    if duration > 0 and rate >= _MIN_SAMPLE_RATE else "lossless")
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
            # Never downgrade on a failed check, but say so: a silent
            # fallback would hide a fake FLAC.
            logger.warning("fake-lossless check failed for %s; rating it lossless",
                           path, exc_info=True)
            tier = "lossless"
    else:
        tier = tier_for(codec, kbps, False)
    return AudioQuality(codec, kbps, _int_or_none(st.get("sample_rate")), depth,
                        lossless, tier)
