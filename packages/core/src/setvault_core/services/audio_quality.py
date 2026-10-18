"""Measure a set's audio quality (codec, bitrate, depth) and rate it with a tier."""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

TIERS: tuple[str, ...] = ("lossless", "high", "good", "ok", "low")

_LOSSLESS_CODECS = {"flac", "alac", "wavpack", "ape"}
_HIGH_MP3_KBPS = 320
_HIGH_OTHER_KBPS = 256
_HIGH_OTHER_CODECS = {"aac", "opus", "vorbis"}

# Fake-lossless check: a lossy encoder low-passes with a brick-wall cutoff
# (128k MP3 near 16-17 kHz, 192k+ near 19-20 kHz). Genuine audio rolls off
# gradually, however tilted its spectrum is, so we look for a *cliff* between
# a band just below a cutoff and a band just above it, not for a quiet top end.
_WINDOW_SECONDS = 30
_WINDOW_POSITIONS = (0.10, 0.50, 0.90)
# (below, above) bands in Hz for the 128k-style and the 192k-style cutoff.
_BANDS_16K = ((14000, 16000), (17500, 19000))
_BANDS_19K = ((17500, 19000), (19500, 21000))
_MIN_SAMPLE_RATE = 44100  # the 19.5-21 kHz band needs a Nyquist above 21 kHz
# Each band edge is a chain of 2-pole filters; a single stage leaks too much.
_FILTER_STAGES = 4
# Cliff = below-band minus above-band mean volume, in dB. Measured on 44.1 kHz
# fixtures (dB below/above): white 128k->FLAC 14-16k vs 17.5-19k: 15.5 cliff,
# 192k->FLAC 17.5-19k vs 19.5-21k: 20.5 cliff; genuine white/pink/brown/48 kHz
# white/steeply sloped noise: between -5 and +3 in both pairs.
_CLIFF_DB_16K = 10.0
_CLIFF_DB_19K = 15.0
_FLOOR_DB = -120.0  # band so quiet volumedetect reports nothing

_MEAN_RE = re.compile(r"mean_volume:\s*(-?[\d.]+|-inf)\s*dB")


@dataclass(frozen=True)
class AudioQuality:
    codec: str
    bitrate_kbps: int | None
    sample_rate: int | None
    bit_depth: int | None
    lossless: bool
    tier: str


def is_lossless_codec(codec: str) -> bool:
    return codec in _LOSSLESS_CODECS or codec.startswith("pcm_")


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


def _band_volume(path: Path, start: float, band: tuple[int, int]) -> float:
    lo, hi = band
    stage = f"highpass=f={lo},lowpass=f={hi}"
    af = ",".join([stage] * _FILTER_STAGES) + ",volumedetect"
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-ss", f"{start:.2f}",
           "-t", str(_WINDOW_SECONDS), "-i", str(path), "-vn", "-af", af,
           "-f", "null", "-"]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)  # noqa: S603
    m = _MEAN_RE.search(res.stderr)
    if not m or m.group(1) == "-inf":
        return _FLOOR_DB
    return float(m.group(1))


def _cliff_db(path: Path, starts: list[float], bands: tuple[tuple[int, int], ...]) -> float:
    below, above = bands
    diffs = [_band_volume(path, t, below) - _band_volume(path, t, above) for t in starts]
    return sum(diffs) / len(diffs)


def _fake_lossless_tier(path: Path, duration: float) -> str:
    """Rate a lossless file by looking for a lossy low-pass cliff: lossless, good or ok."""
    last_start = max(0.0, duration - _WINDOW_SECONDS)
    starts = [min(max(0.0, duration * pos - _WINDOW_SECONDS / 2), last_start)
              for pos in _WINDOW_POSITIONS]
    if _cliff_db(path, starts, _BANDS_16K) > _CLIFF_DB_16K:
        return "ok"
    if _cliff_db(path, starts, _BANDS_19K) > _CLIFF_DB_19K:
        return "good"
    return "lossless"


def measure_quality(path: Path) -> AudioQuality:
    cmd = ["ffprobe", "-v", "error", "-show_streams", "-show_format",
           "-of", "json", str(path)]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True)  # noqa: S603
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
        except (subprocess.CalledProcessError, OSError):
            tier = "lossless"
    else:
        tier = tier_for(codec, kbps, False)
    return AudioQuality(codec, kbps, _int_or_none(st.get("sample_rate")), depth,
                        lossless, tier)
