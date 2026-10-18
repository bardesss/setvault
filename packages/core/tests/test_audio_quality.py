import subprocess
from pathlib import Path

import pytest
from setvault_core.services.audio_quality import (
    TIERS,
    is_lossless_codec,
    measure_quality,
    tier_for,
)


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
    # Steep natural roll-off (pink through a 15 kHz lowpass) plus low white hiss.
    _ffmpeg("-f", "lavfi", "-i", "anoisesrc=color=pink:d=60:r=44100:a=0.5",
            "-f", "lavfi", "-i", "anoisesrc=color=white:d=60:r=44100:a=0.003",
            "-filter_complex", "[0]lowpass=f=15000:poles=2[a];[a][1]amix=inputs=2:normalize=0",
            "-ac", "2", "-sample_fmt", "s16", str(d / "hiss.flac"))
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


@pytest.mark.parametrize("codec", [
    "flac", "alac", "wavpack", "ape", "pcm_s16le", "pcm_s24be", "tta", "tak",
    "truehd", "mlp", "wmalossless", "shorten", "mp4als", "dsd_lsbf", "dsd_msbf",
    "dsd_lsbf_planar", "dsd_msbf_planar",
])
def test_lossless_codecs_rate_lossless(codec):
    assert is_lossless_codec(codec) is True
    assert tier_for(codec, None, is_lossless_codec(codec)) == "lossless"


@pytest.mark.parametrize("codec", ["mp3", "aac", "opus", "vorbis", "wmav2", "ac3"])
def test_lossy_codecs_are_not_lossless(codec):
    assert is_lossless_codec(codec) is False


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


def test_steep_natural_rolloff_with_hiss_stays_lossless(noise_dir):
    q = measure_quality(noise_dir / "hiss.flac")
    assert q.lossless is True
    assert q.tier == "lossless"


def test_measurement_timeout_raises_for_probe_to_handle(noise_dir, monkeypatch):
    import subprocess as sp

    from setvault_core.services import audio_quality as aq

    def slow(*_a, **_k):
        raise sp.TimeoutExpired("ffprobe", 1)

    monkeypatch.setattr(aq.subprocess, "run", slow)
    with pytest.raises(sp.TimeoutExpired):
        measure_quality(noise_dir / "noise.flac")


def test_quality_check_has_one_overall_budget(monkeypatch, tmp_path):
    """The window decodes share QUALITY_CHECK_BUDGET_SECONDS: each gets at
    most what is left, and once it is spent the check stops."""
    import subprocess as sp
    from types import SimpleNamespace

    from setvault_core.services import audio_quality as aq

    clock = {"t": 0.0}
    timeouts: list[float] = []

    def fake_run(cmd, **kw):
        timeouts.append(kw["timeout"])
        clock["t"] += 100.0  # every decode takes 100 s
        return sp.CompletedProcess(cmd, 0, stdout="", stderr="mean_volume: -20.0 dB")

    monkeypatch.setattr(aq.subprocess, "run", fake_run)
    monkeypatch.setattr(aq, "time", SimpleNamespace(monotonic=lambda: clock["t"]))

    with pytest.raises(sp.TimeoutExpired):
        aq._fake_lossless_tier(tmp_path / "x.flac", 3600.0)
    assert timeouts == [120, 80]


def test_failed_fake_lossless_check_logs_and_keeps_lossless(noise_dir, monkeypatch, caplog):
    import subprocess as sp

    from setvault_core.services import audio_quality as aq

    def broken(*_a, **_k):
        raise sp.TimeoutExpired("ffmpeg", 180)

    monkeypatch.setattr(aq, "_fake_lossless_tier", broken)
    with caplog.at_level("WARNING", logger="setvault_core.services.audio_quality"):
        q = measure_quality(noise_dir / "noise.flac")
    assert q.tier == "lossless"
    assert "fake-lossless check failed" in caplog.text
