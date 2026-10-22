import pytest
from setvault_providers import musicbrainz


@pytest.fixture(autouse=True)
def _no_musicbrainz_throttle(monkeypatch):
    async def _instant(_seconds):
        return None

    monkeypatch.setattr(musicbrainz, "_sleep", _instant)
