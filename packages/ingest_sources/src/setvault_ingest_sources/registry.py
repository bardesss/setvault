from __future__ import annotations

from setvault_ingest_sources.bandcamp import BandcampSource
from setvault_ingest_sources.base import IngestSource
from setvault_ingest_sources.internet_archive import InternetArchiveSource
from setvault_ingest_sources.mixcloud import MixcloudSource
from setvault_ingest_sources.soundcloud import SoundCloudSource
from setvault_ingest_sources.youtube import YouTubeSource

# 7B ships four stock sources. Later phases may switch to entry-point
# discovery; the get_source()/all_source_kinds() contract stays.
_SOURCES: dict[str, IngestSource] = {}
for _src in (
    YouTubeSource(), SoundCloudSource(), MixcloudSource(), InternetArchiveSource(),
    BandcampSource(),
):
    _SOURCES[_src.kind] = _src


def all_source_kinds() -> list[str]:
    return sorted(_SOURCES)


def get_source(kind: str) -> IngestSource | None:
    return _SOURCES.get(kind)
