"""Live Bandcamp reachability check (no account, no login, no download).

Records which formats yt-dlp can list for a paid track and for free /
name-your-price tracks, so we know whether Bandcamp can supply lossless
upgrades. Skipped unless SETVAULT_NETWORK_TESTS=1.

Run: SETVAULT_NETWORK_TESTS=1 uv run --no-sync pytest \
  packages/ingest_sources/tests/test_bandcamp_live.py -q -s
"""
import os

import pytest

pytestmark = [
    pytest.mark.network,
    pytest.mark.skipif(
        os.environ.get("SETVAULT_NETWORK_TESTS") != "1",
        reason="set SETVAULT_NETWORK_TESTS=1 to run live network tests",
    ),
]

LOSSLESS = {"flac", "wav", "aiff", "alac"}

# URLs taken from yt-dlp's own Bandcamp extractor test cases.
CASES = {
    "paid": "https://relapsealumni.bandcamp.com/track/hail-to-fire",
    "free": "http://benprunty.bandcamp.com/track/lanius-battle",
    "free_test_song": "http://youtube-dl.bandcamp.com/track/youtube-dl-test-song",
}


def _formats(url: str) -> list[dict]:
    import yt_dlp

    opts = {"skip_download": True, "quiet": True, "no_warnings": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    return info.get("formats") or []


@pytest.mark.parametrize("label", list(CASES))
def test_bandcamp_formats_reachable(label):
    url = CASES[label]
    formats = _formats(url)
    rows = [
        {k: f.get(k) for k in ("format_id", "acodec", "abr", "tbr", "ext")}
        for f in formats
    ]
    print(f"\n[{label}] {url}")
    for row in rows:
        print("   ", row)
    lossless = [r for r in rows if (r["acodec"] in LOSSLESS or r["ext"] in LOSSLESS)]
    print(f"    lossless reachable: {bool(lossless)}")
    # Only the stable fact: at least one audio format is listed.
    assert any(f.get("vcodec") in (None, "none") for f in formats)


def test_bandcamp_search_live_returns_candidates():
    from setvault_ingest_sources.bandcamp import BandcampSource

    out = BandcampSource().search("techno", limit=5)
    for c in out:
        print("   ", ascii((c.external_id, c.title, c.uploader, c.webpage_url)))
    assert len(out) >= 1
    assert all(".bandcamp.com/" in c.webpage_url for c in out)
