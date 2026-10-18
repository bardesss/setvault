import subprocess
from pathlib import Path

import pytest
from setvault_core.services.audio_quality import TIERS, measure_quality, tier_for


def _ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args],  # noqa: S603, S607
                   check=True, capture_output=True)


@pytest.fixture(scope="module")
def noise_dir(tmp_path_factory) -> Path:
    """60 s of stereo white noise, plus encodes of it, built once per module."""
    import shutil

    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")
    d = tmp_path_factory.mktemp("noise")
    _ffmpeg("-f", "lavfi", "-i", "anoisesrc=color=white:d=60:r=44100:a=0.5",
            "-ac", "2", "-sample_fmt", "s16", str(d / "noise.flac"))
    _ffmpeg("-i", str(d / "noise.flac"), "-c:a", "libmp3lame", "-b:a", "320k",
            str(d / "n320.mp3"))
    _ffmpeg("-i", str(d / "noise.flac"), "-c:a", "libmp3lame", "-b:a", "128k",
            str(d / "n128.mp3"))
    _ffmpeg("-i", str(d / "n128.mp3"), "-sample_fmt", "s16", str(d / "fake.flac"))
    _ffmpeg("-i", str(d / "noise.flac"), "-c:a", "libmp3lame", "-b:a", "192k",
            str(d / "n192.mp3"))
    _ffmpeg("-i", str(d / "n192.mp3"), "-sample_fmt", "s16", str(d / "fake192.flac"))
    for colour in ("pink", "brown"):
        _ffmpeg("-f", "lavfi", "-i", f"anoisesrc=color={colour}:d=60:r=44100:a=0.5",
                "-ac", "2", "-sample_fmt", "s16", str(d / f"{colour}.flac"))
    # Music-like: most energy in the lows, gradual (12 dB/oct) roll-off, no cliff.
    _ffmpeg("-f", "lavfi", "-i", "anoisesrc=color=pink:d=60:r=44100:a=0.5",
            "-af", "lowpass=f=3000", "-ac", "2", "-sample_fmt", "s16", str(d / "sloped.flac"))
    _ffmpeg("-f", "lavfi", "-i", "anoisesrc=color=white:d=60:r=48000:a=0.5",
            "-ac", "2", "-sample_fmt", "s16", str(d / "white48.flac"))
    return d


@pytest.mark.parametrize(("codec", "kbps", "lossless", "tier"), [
    ("flac", None, True, "lossless"),
    ("mp3", 320, False, "high"),
    ("mp3", 256, False, "good"),
    ("opus", 256, False, "high"),
    ("aac", 192, False, "good"),
    ("mp3", 128, False, "ok"),
    ("mp3", 96, False, "low"),
    ("mp3", None, False, "ok"),
])
def test_tier_for_table(codec, kbps, lossless, tier):
    assert tier_for(codec, kbps, lossless) == tier
    assert tier in TIERS


def test_measure_quality_real_flac(noise_dir):
    q = measure_quality(noise_dir / "noise.flac")
    assert q.codec == "flac"
    assert q.lossless is True
    assert q.tier == "lossless"
    assert q.sample_rate == 44100
    assert q.bit_depth == 16


def test_measure_quality_mp3_320(noise_dir):
    q = measure_quality(noise_dir / "n320.mp3")
    assert q.codec == "mp3"
    assert q.lossless is False
    assert q.tier == "high"
    assert 304 <= q.bitrate_kbps <= 336


def test_measure_quality_mp3_128(noise_dir):
    q = measure_quality(noise_dir / "n128.mp3")
    assert q.tier == "ok"
    assert 122 <= q.bitrate_kbps <= 134


def test_fake_lossless_from_128k_is_rated_ok(noise_dir):
    q = measure_quality(noise_dir / "fake.flac")
    assert q.codec == "flac"
    assert q.lossless is True
    assert q.tier == "ok"


def test_fake_lossless_from_192k_is_rated_good(noise_dir):
    q = measure_quality(noise_dir / "fake192.flac")
    assert q.lossless is True
    assert q.tier == "good"


@pytest.mark.parametrize("name", ["pink.flac", "brown.flac", "white48.flac", "sloped.flac"])
def test_genuine_lossless_noise_stays_lossless(noise_dir, name):
    """Sloped spectra (pink/brown) and 48 kHz must not look like a lowpass."""
    q = measure_quality(noise_dir / name)
    assert q.lossless is True
    assert q.tier == "lossless"
