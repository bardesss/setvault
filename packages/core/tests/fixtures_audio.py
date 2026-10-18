"""Synthetic "live sets" for the fuzzy audio matcher tests.

Chromaprint fingerprints pitch-class (chroma) movement, so static tones or
plain noise make useless fixtures: every such file looks alike. Each set here
is a pseudo-random melody + bass line (note choice hashed from the time step
and a per-set key), pulsed by ``apulsator`` with a slowly drifting tempo, over
a seeded noise bed. Different keys give genuinely different music.

Set B shares set A's first 60 s (a shared intro) and is different after that.
Set C is unrelated to A. ``build_sets`` writes every file the tests need.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

SET_SECONDS = 300
SHARED_INTRO_SECONDS = 60
TRIM_SECONDS = 20


def ensure_tools(*tools: str) -> None:
    """Module-scope twin of conftest's ``require_tools``: skip locally, fail in CI."""
    missing = [t for t in tools if not shutil.which(t)]
    if not missing:
        return
    msg = f"{' + '.join(missing)} not installed"
    if os.environ.get("SETVAULT_REQUIRE_AUDIO_TOOLS") == "1":
        pytest.fail(msg)
    pytest.skip(msg)


def _ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args],  # noqa: S603, S607
                   check=True, capture_output=True, timeout=300)


def _music_expr(key: float, bass_key: float) -> str:
    # Melody: a new semitone (0-23 above A3) every 1/4 s; bass: every 1 s.
    melody = f"220*pow(2,floor(24*abs(sin(floor(t*4)*{key})))/12)"
    bass = f"55*pow(2,floor(12*abs(sin(floor(t)*{bass_key})))/12)"
    return (f"0.30*sin(2*PI*{melody}*t)+0.12*sin(4*PI*{melody}*t)"
            f"+0.35*sin(2*PI*{bass}*t)")


def _make_set(out: Path, key: float, bass_key: float, seed: int, pulse_hz: float) -> None:
    _ffmpeg(
        "-f", "lavfi", "-i",
        f"aevalsrc='{_music_expr(key, bass_key)}':s=44100:d={SET_SECONDS}",
        "-f", "lavfi", "-i",
        f"anoisesrc=color=pink:seed={seed}:a=0.08:r=44100:d={SET_SECONDS}",
        "-filter_complex",
        # Pulse the music (a "beat"), with the tempo itself wobbling via vibrato.
        f"[0]apulsator=hz={pulse_hz}:amount=0.6,vibrato=f=0.2:d=0.3[m];"
        "[m][1]amix=inputs=2:normalize=0",
        "-ac", "2", "-sample_fmt", "s16", str(out),
    )


def build_sets(d: Path) -> dict[str, Path]:
    """Write set A (+ re-encodes, trimmed copy, excerpt), B and C into ``d``."""
    p = {name: d / f"{name}.{ext}" for name, ext in [
        ("a", "flac"), ("a_mp3_320", "mp3"), ("a_mp3_128", "mp3"), ("a_opus_96", "opus"),
        ("a_trim20", "flac"), ("a_excerpt", "flac"), ("c", "flac"), ("b", "flac"),
    ]}
    _make_set(p["a"], key=12.9898, bass_key=78.233, seed=1, pulse_hz=2.0)
    _make_set(p["c"], key=43.7585, bass_key=91.117, seed=2, pulse_hz=2.13)
    _ffmpeg("-i", str(p["a"]), "-c:a", "libmp3lame", "-b:a", "320k", str(p["a_mp3_320"]))
    _ffmpeg("-i", str(p["a"]), "-c:a", "libmp3lame", "-b:a", "128k", str(p["a_mp3_128"]))
    _ffmpeg("-i", str(p["a"]), "-c:a", "libopus", "-b:a", "96k", str(p["a_opus_96"]))
    _ffmpeg("-ss", str(TRIM_SECONDS), "-i", str(p["a"]), str(p["a_trim20"]))
    # A one-minute excerpt from the middle of A: same audio, very different length.
    _ffmpeg("-ss", "120", "-t", "60", "-i", str(p["a"]), str(p["a_excerpt"]))
    # B: A's first 60 s, then C's music for the rest (C from 60 s on).
    _ffmpeg(
        "-i", str(p["a"]), "-i", str(p["c"]), "-filter_complex",
        f"[0]atrim=0:{SHARED_INTRO_SECONDS},asetpts=PTS-STARTPTS[i];"
        f"[1]atrim={SHARED_INTRO_SECONDS},asetpts=PTS-STARTPTS[r];"
        "[i][r]concat=n=2:v=0:a=1",
        "-sample_fmt", "s16", str(p["b"]),
    )
    return p
