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

# Fake-lossless check: a lossless container whose top octave is empty was most
# likely encoded from a lossy source with a low-pass (128k MP3 cuts near 16 k).
_WINDOW_SECONDS = 30
_WINDOW_POSITIONS = (0.10, 0.50, 0.90)
_CUTOFF_16K = 16500
_CUTOFF_19K = 19500
# ffmpeg's highpass is only 2-pole, which leaks too much energy from below the
# cutoff; chaining it steepens the slope enough to see an empty band.
_HIGHPASS_STAGES = 6
_EMPTY_DB_19K = 50.0
# White noise through a 128k MP3 sits ~34 dB below the full band at 16.5 k
# after the chained filter, so 50 dB would never trip; 30 dB catches it.
_EMPTY_DB_16K = 30.0

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


def _mean_volume(path: Path, start: float, highpass: int | None) -> float | None:
    af = "volumedetect"
    if highpass is not None:
        af = ",".join([f"highpass=f={highpass}"] * _HIGHPASS_STAGES) + "," + af
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-ss", f"{start:.2f}",
           "-t", str(_WINDOW_SECONDS), "-i", str(path), "-vn", "-af", af,
           "-f", "null", "-"]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)  # noqa: S603
    m = _MEAN_RE.search(res.stderr)
    if not m or m.group(1) == "-inf":
        return None
    return float(m.group(1))


def _fake_lossless_tier(path: Path, duration: float) -> str:
    """Rate a lossless file by its high-band energy: lossless, good or ok."""
    full: list[float] = []
    b16: list[float] = []
    b19: list[float] = []
    last_start = max(0.0, duration - _WINDOW_SECONDS)
    for pos in _WINDOW_POSITIONS:
        start = min(max(0.0, duration * pos - _WINDOW_SECONDS / 2), last_start)
        f = _mean_volume(path, start, None)
        h16 = _mean_volume(path, start, _CUTOFF_16K)
        h19 = _mean_volume(path, start, _CUTOFF_19K)
        if f is None:
            continue  # digital silence tells us nothing
        full.append(f)
        # An unmeasurably quiet band is as empty as it gets.
        b16.append(h16 if h16 is not None else -120.0)
        b19.append(h19 if h19 is not None else -120.0)
    if not full:
        return "lossless"
    mean_full = sum(full) / len(full)
    if mean_full - sum(b16) / len(b16) > _EMPTY_DB_16K:
        return "ok"
    if mean_full - sum(b19) / len(b19) > _EMPTY_DB_19K:
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
        try:
            tier = _fake_lossless_tier(path, duration) if duration > 0 else "lossless"
        except (subprocess.CalledProcessError, OSError):
            tier = "lossless"
    else:
        tier = tier_for(codec, kbps, False)
    return AudioQuality(codec, kbps, _int_or_none(st.get("sample_rate")), depth,
                        lossless, tier)
