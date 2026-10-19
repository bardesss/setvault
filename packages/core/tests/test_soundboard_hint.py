import pytest
from setvault_core.services.soundboard_hint import has_soundboard_hint


@pytest.mark.parametrize("text", [
    "Artist Live 1999 SBD", "sbd master", "Soundboard recording", "PRE-FM broadcast",
    "prefm source", "desk recording", "Line In capture", "line-in tape", "(SBD)",
])
def test_positive(text):
    assert has_soundboard_hint(text)


@pytest.mark.parametrize(
    "text", [None, "", "absbdx", "soundboards", "prefmx", "online", "plain set"]
)
def test_negative(text):
    assert not has_soundboard_hint(text)
