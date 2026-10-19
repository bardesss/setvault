import array
import dataclasses
import importlib.util
import random
import time
from pathlib import Path

import pytest
from setvault_core.models.catalog import SetFingerprint
from setvault_core.services.audio_match import (
    ITEMS_PER_SECOND,
    SAME_AUDIO_MAX_BER,
    WORST_WINDOW_MAX_BER,
    MatchResult,
    _probe,
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
    assert r.worst_window_ber < 0.05
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


def test_items_per_second_is_chromaprints_hop():
    assert ITEMS_PER_SECOND == 11025 / 1365


def test_raw_to_bytes_rejects_non_uint32_arrays():
    with pytest.raises(ValueError):
        raw_to_bytes(array.array("Q", [1]))


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
    assert r.worst_window_ber < 0.12
    assert 1 - r.similarity == pytest.approx(0.08, abs=0.01)


def test_synthetic_unrelated_returns_none():
    assert compare(_random_fp(3000, seed=1), _random_fp(3000, seed=3)) is None


def test_too_short_inputs_return_none():
    assert compare(array.array("I", [1, 2, 3]), _random_fp(3000, seed=1)) is None
    assert compare(_random_fp(3000, seed=1), array.array("I")) is None


def test_is_same_audio_thresholds():
    assert not is_same_audio(None)
    ok = MatchResult(similarity=0.9, offset_seconds=0, overlap=1.0, worst_window_ber=0.1)
    assert is_same_audio(ok)
    assert not is_same_audio(dataclasses.replace(ok, similarity=0.5))
    assert not is_same_audio(dataclasses.replace(ok, overlap=0.5))
    assert not is_same_audio(dataclasses.replace(ok, worst_window_ber=0.4))


def _ber_at(a: array.array, b: array.array, k: int) -> float:
    """Full-overlap BER at offset k (A[i+k] ~ B[i]), computed independently."""
    a0, b0 = max(0, k), max(0, -k)
    n = min(len(a) - a0, len(b) - b0)
    return sum((a[a0 + i] ^ b[b0 + i]).bit_count() for i in range(n)) / (32 * n)


def test_probe_agreement_rejects_what_the_full_ber_would_accept():
    # B = A's first 2000 items, then A's 2100-3000: every probe finds itself
    # with BER 0, but probe 3 (at 2250) lands at offset +100, probes 1-2 at 0.
    a = _random_fp(3000, seed=1)
    b = a[:2000] + a[2100:]
    assert _ber_at(a, b, 0) < SAME_AUDIO_MAX_BER  # a whole-overlap score alone passes
    # Only the agreement check returns None here (the window guard would still
    # return a MatchResult), so removing it fails this test.
    assert compare(a, b) is None


def test_mostly_shared_audio_with_different_last_third_does_not_match():
    a = _random_fp(3000, seed=1)
    b = a[:2000] + _random_fp(1000, seed=5)  # ~67% shared
    assert _ber_at(a, b, 0) < SAME_AUDIO_MAX_BER
    # The overall BER alone would pass, so prove which gate rejects it: the
    # first two probes (items 750, 1500) find themselves at offset 0, the
    # third (item 2250, in the replaced tail) doesn't, so the per-probe BER
    # gate returns None before any full-overlap score is computed.
    ab, bb = raw_to_bytes(a), raw_to_bytes(b)
    radius = int(0.10 * len(a) + 120 * ITEMS_PER_SECOND)
    assert _probe(ab, bb, len(b), 750, radius) == (0, 0.0)
    assert _probe(ab, bb, len(b), 1500, radius) == (0, 0.0)
    assert _probe(ab, bb, len(b), 2250, radius)[1] >= 0.35
    assert compare(a, b) is None


def test_every_probe_must_find_itself_not_just_the_best():
    # Only probe 3's slice (A[2250:2370]) is garbled (40% of bits): offsets
    # still agree on 0 and the whole-overlap and window BERs stay low, so only
    # the per-probe BER gate rejects it.
    a = _random_fp(3000, seed=1)
    b = a[:2250] + _flip_bits(a[2250:2370], rate=0.40, seed=6) + a[2370:]
    assert _ber_at(a, b, 0) < 0.02
    assert compare(a, b) is None


def test_different_ending_is_caught_by_the_worst_window():
    # Identical except the last ~15%: overall BER ~0.075 would pass on its own.
    a = _random_fp(3000, seed=1)
    b = a[:2550] + _random_fp(450, seed=7)
    r = compare(a, b)
    assert r is not None
    assert 1 - r.similarity < SAME_AUDIO_MAX_BER
    assert r.worst_window_ber > WORST_WINDOW_MAX_BER
    assert not is_same_audio(r)


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
