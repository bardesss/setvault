from setvault_ingest_sources.registry import all_source_kinds, get_source


def test_all_five_sources_registered():
    assert all_source_kinds() == [
        "bandcamp", "internet_archive", "mixcloud", "soundcloud", "youtube",
    ]


def test_get_source_returns_instances():
    for kind in ("youtube", "soundcloud", "mixcloud", "internet_archive", "bandcamp"):
        src = get_source(kind)
        assert src is not None and src.kind == kind


def test_unknown_kind_returns_none():
    assert get_source("nope") is None
