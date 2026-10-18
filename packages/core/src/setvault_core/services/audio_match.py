"""Fuzzy "same set?" matching on raw chromaprint fingerprints (spec §4.2).

The old exact hash only catches byte-identical audio. Here two recordings are
compared item by item at their best alignment: a re-encode flips a few bits
per item, a different set flips about half of them.

A false match lets a later upgrade swap away a good copy, so this errs toward
"not the same": three probe slices from across set A must all find the same
offset in B (one shared intro can't fake that), and the final bit-error rate
is measured over the whole overlap.

Measured on the synthetic fixtures (tests/fixtures_audio.py, 5-minute sets,
chromaprint 1.5.1, Debian bookworm). Full-overlap BER at the chosen offset:
  A FLAC vs MP3 320 / MP3 128 / Opus 96 ...... 0.0001 / 0.0005 / 0.0036 (match)
  A vs A minus first 20 s (both directions) .. 0.078, offset ±20.06 s (match;
      the cut lands mid-hop, the worst case for item alignment)
  A vs A's 60 s excerpt ...................... 0.040, overlap 0.19 (no match)
  A vs B (shared 60 s intro, BER 0.011 there)  probes disagree -> None;
      full BER at offset 0 would be 0.365
  A vs C (unrelated) ......................... probes disagree -> None;
      full BER at offset 0 is 0.455; best probe BERs 0.30-0.45
So 0.20 / 0.8 leave a wide margin both ways and are kept as specified.
"""
from __future__ import annotations

import array
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# Bump when the fingerprint parameters or the comparison change in a way that
# makes stored raw fingerprints incomparable with new ones.
MATCHER_VERSION = 1

# Chromaprint resamples to 11025 Hz and hops 4096/3 samples per item
# (~8.07/s; fpcalc reports ~8.0 over a file since the edges lose a few items).
# 7.8 would put a 20 s trim at 20.8 s and drift tracklist shifts by ~3%.
ITEMS_PER_SECOND = 11025 / (4096 / 3)

SAME_AUDIO_MAX_BER = 0.20
MIN_OVERLAP = 0.8

_PROBE_ITEMS = 120
_PROBE_POSITIONS = (0.25, 0.50, 0.75)
_PROBE_MAX_BER = 0.35
_AGREE_ITEMS = 8
_SEARCH_EXTRA_SECONDS = 120
_FPCALC_TIMEOUT = 1800  # a 3-hour set decodes in well under this

_TYPECODE = "I" if array.array("I").itemsize == 4 else "L"


@dataclass(frozen=True)
class MatchResult:
    similarity: float  # 1 - bit-error rate over the overlap
    offset_seconds: float  # where B's start sits in A (positive: B starts later)
    # Overlap length / the LONGER fingerprint's length. Against the shorter one
    # (as first planned), a 1-minute excerpt of a set would score 1.0 and
    # "match" the full set (measured: BER 0.04); the spec wants durations close.
    overlap: float


def raw_to_bytes(fp: array.array) -> bytes:
    """Little-endian uint32 bytes, as stored in ``SetFingerprint.raw``."""
    if sys.byteorder == "little":
        return fp.tobytes()
    swapped = array.array(fp.typecode, fp)
    swapped.byteswap()
    return swapped.tobytes()


def raw_from_bytes(raw: bytes) -> array.array:
    fp = array.array(_TYPECODE)
    fp.frombytes(raw)
    if sys.byteorder != "little":
        fp.byteswap()
    return fp


def compute_raw_fingerprint(path: Path) -> tuple[array.array, float]:
    """Raw chromaprint of the whole file: (uint32 items, duration seconds)."""
    # -length 0: the whole file. The default (120 s) can't tell apart two sets
    # that share an intro. No check=True: chromaprint 1.5.1 exits 3 at EOF
    # after printing a valid fingerprint (see jobs/fingerprint.py).
    out = subprocess.run(  # noqa: S603
        ["fpcalc", "-raw", "-json", "-length", "0", str(path)],  # noqa: S607
        capture_output=True, text=True, timeout=_FPCALC_TIMEOUT,
    )
    try:
        data = json.loads(out.stdout)
        items = data["fingerprint"]
        duration = float(data["duration"])
    except (ValueError, KeyError, TypeError) as exc:
        raise RuntimeError(
            f"fpcalc failed (exit {out.returncode}): {out.stderr.strip()[-500:]}",
        ) from exc
    if not items:
        raise RuntimeError(f"fpcalc returned an empty fingerprint (exit {out.returncode})")
    # Some builds print the items as signed ints; normalise to uint32.
    return array.array(_TYPECODE, (int(v) & 0xFFFFFFFF for v in items)), duration


def _as_int(fp_bytes: bytes, start: int, n: int) -> int:
    """Items [start, start+n) as one big int, so XOR + bit_count is one C call."""
    return int.from_bytes(fp_bytes[start * 4:(start + n) * 4], "little")


def _probe(a_bytes: bytes, b_bytes: bytes, len_b: int, p: int, radius: int,
           ) -> tuple[int, float]:
    """Best offset k (A[p+i] ~ B[p-k+i]) for A's probe slice at p, and its BER."""
    probe = _as_int(a_bytes, p, _PROBE_ITEMS)
    bits = 32 * _PROBE_ITEMS
    best_k, best_errors = 0, bits + 1
    q_lo = max(0, p - radius)
    q_hi = min(len_b - _PROBE_ITEMS, p + radius)
    for q in range(q_lo, q_hi + 1):
        errors = (probe ^ _as_int(b_bytes, q, _PROBE_ITEMS)).bit_count()
        if errors < best_errors:
            best_k, best_errors = p - q, errors
    return best_k, best_errors / bits


def compare(a: array.array, b: array.array) -> MatchResult | None:
    """Align B against A and score the overlap; None when nothing lines up."""
    len_a, len_b = len(a), len(b)
    if len_a < _PROBE_ITEMS or len_b < _PROBE_ITEMS:
        return None
    a_bytes, b_bytes = raw_to_bytes(a), raw_to_bytes(b)
    radius = int(0.10 * len_a + _SEARCH_EXTRA_SECONDS * ITEMS_PER_SECOND)

    # 1. Coarse offset search with three short probes from across A.
    probes = []
    for pos in _PROBE_POSITIONS:
        p = min(int(pos * len_a), len_a - _PROBE_ITEMS)
        if max(0, p - radius) > min(len_b - _PROBE_ITEMS, p + radius):
            continue  # this probe's search window falls outside B
        probes.append(_probe(a_bytes, b_bytes, len_b, p, radius))
    # 4. Nothing even roughly similar: bail out early.
    if not probes or min(ber for _, ber in probes) >= _PROBE_MAX_BER:
        return None
    # 2. All three probes must agree on one offset (rejects a shared intro).
    if len(probes) < len(_PROBE_POSITIONS):
        return None
    offsets = sorted(k for k, _ in probes)
    k = offsets[1]
    if k - offsets[0] > _AGREE_ITEMS or offsets[-1] - k > _AGREE_ITEMS:
        return None

    # 3. Final score over the full overlap at the agreed offset.
    a_start, b_start = max(0, k), max(0, -k)
    n = min(len_a - a_start, len_b - b_start)
    if n <= 0:
        return None
    errors = (_as_int(a_bytes, a_start, n) ^ _as_int(b_bytes, b_start, n)).bit_count()
    return MatchResult(
        similarity=1 - errors / (32 * n),
        offset_seconds=k / ITEMS_PER_SECOND,
        overlap=n / max(len_a, len_b),
    )


def is_same_audio(r: MatchResult | None) -> bool:
    return (r is not None and 1 - r.similarity <= SAME_AUDIO_MAX_BER
            and r.overlap >= MIN_OVERLAP)
