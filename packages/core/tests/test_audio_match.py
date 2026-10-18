import array
import importlib.util
import random
import time
from pathlib import Path

import pytest
from setvault_core.models.catalog import SetFingerprint
from setvault_core.services.audio_match import (
    ITEMS_PER_SECOND,
    MatchResult,
    compare,
    compute_raw_fingerprint,
    is_same_audio,
    raw_from_bytes,
    raw_to_bytes,
)

# pytest runs with --import-mode=importlib, so sibling modules aren't on sys.path.
_spec = importlib.util.spec_from_file_location(
    "fixtures_audio", Path(__file__).with_name("fixtures_audio.py"))
fixtures_audio = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fixtures_audio)


@pytest.fixture(scope="module")
def fps(tmp_path_factory) -> dict[str, array.array]:
    """Raw fingerprints of every fixture set, built once per module."""
    fixtures_audio.ensure_tools("ffmpeg", "fpcalc")
    paths = fixtures_audio.build_sets(tmp_path_factory.mktemp("sets"))
    return {name: compute_raw_fingerprint(p)[0] for name, p in paths.items()}


# --- fpcalc-backed tests ---------------------------------------------------


def test_compute_raw_fingerprint_covers_the_whole_file(fps):
    # The fpcalc default stops at 120 s; the matcher needs the full set.
    seconds = len(fps["a"]) / ITEMS_PER_SECOND
    assert seconds == pytest.approx(fixtures_audio.SET_SECONDS, abs=3)


@pytest.mark.parametrize("copy", ["a_mp3_320", "a_mp3_128", "a_opus_96"])
def test_reencodes_of_same_set_match(fps, copy):
    r = compare(fps["a"], fps[copy])
    assert is_same_audio(r), r
    assert abs(r.offset_seconds) < 1


def test_trimmed_copy_matches_with_offset(fps):
    r = compare(fps["a"], fps["a_trim20"])
    assert is_same_audio(r), r
    assert r.offset_seconds == pytest.approx(fixtures_audio.TRIM_SECONDS, abs=1)
    # Reversed roles: B is now the longer copy, so the shift flips sign.
    r = compare(fps["a_trim20"], fps["a"])
    assert is_same_audio(r), r
    assert r.offset_seconds == pytest.approx(-fixtures_audio.TRIM_SECONDS, abs=1)


def test_different_audio_with_shared_intro_does_not_match(fps):
    assert not is_same_audio(compare(fps["a"], fps["b"]))
    assert not is_same_audio(compare(fps["b"], fps["a"]))


def test_unrelated_audio_returns_none_or_no_match(fps):
    assert not is_same_audio(compare(fps["a"], fps["c"]))
    assert not is_same_audio(compare(fps["c"], fps["a"]))


def test_excerpt_of_a_set_is_not_the_same_set(fps):
    # Same audio, but one minute of a five-minute set must not count as a copy.
    assert not is_same_audio(compare(fps["a"], fps["a_excerpt"]))
    assert not is_same_audio(compare(fps["a_excerpt"], fps["a"]))


# --- pure-Python tests (no tools needed) ------------------------------------


def _random_fp(n: int, seed: int) -> array.array:
    rng = random.Random(seed)  # noqa: S311 - reproducible test data
    return raw_from_bytes(raw_to_bytes(array.array("I", [rng.getrandbits(32) for _ in range(n)])))


def _flip_bits(fp: array.array, rate: float, seed: int) -> array.array:
    rng = random.Random(seed)  # noqa: S311 - reproducible test data
    out = array.array(fp.typecode, fp)
    for i in range(len(out)):
        for bit in range(32):
            if rng.random() < rate:
                out[i] ^= 1 << bit
    return out


def test_raw_bytes_round_trip_is_little_endian_uint32():
    fp = array.array("I", [0, 1, 0xFFFFFFFF, 0x12345678])
    raw = raw_to_bytes(fp)
    assert raw[:8] == b"\x00\x00\x00\x00\x01\x00\x00\x00"
    assert raw[12:] == b"\x78\x56\x34\x12"
    assert list(raw_from_bytes(raw)) == list(fp)


def test_synthetic_noisy_shifted_copy_matches():
    a = _random_fp(3000, seed=1)
    b = _flip_bits(a[100:], rate=0.08, seed=2)
    r = compare(a, b)
    assert isinstance(r, MatchResult)
    assert is_same_audio(r), r
    assert r.offset_seconds == pytest.approx(100 / ITEMS_PER_SECOND, abs=0.01)
    assert 1 - r.similarity == pytest.approx(0.08, abs=0.01)


def test_synthetic_unrelated_returns_none():
    assert compare(_random_fp(3000, seed=1), _random_fp(3000, seed=3)) is None


def test_too_short_inputs_return_none():
    assert compare(array.array("I", [1, 2, 3]), _random_fp(3000, seed=1)) is None
    assert compare(_random_fp(3000, seed=1), array.array("I")) is None


def test_is_same_audio_thresholds():
    assert not is_same_audio(None)
    assert is_same_audio(MatchResult(similarity=0.9, offset_seconds=0, overlap=1.0))
    assert not is_same_audio(MatchResult(similarity=0.5, offset_seconds=0, overlap=1.0))
    assert not is_same_audio(MatchResult(similarity=0.9, offset_seconds=0, overlap=0.5))


def test_compare_is_fast_on_a_three_hour_set():
    # ~85k items is a 3-hour set; compare runs on every ingest per candidate.
    a = _random_fp(85_000, seed=4)
    b = a[500:]
    start = time.perf_counter()
    r = compare(a, b)
    assert time.perf_counter() - start < 2.0
    assert is_same_audio(r)


def test_set_fingerprint_has_raw_columns():
    cols = SetFingerprint.__table__.columns
    assert "raw" in cols
    assert cols["raw"].nullable
    assert "raw_version" in cols
    assert cols["raw_version"].nullable
