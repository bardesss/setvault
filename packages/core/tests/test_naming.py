"""Tests for the naming template resolver (§J9).

Pure-function tests — no DB. We build minimal LiveSet stand-ins so the
tests don't depend on the Postgres fixtures from conftest.
"""
from __future__ import annotations

import uuid
from datetime import date

from setvault_core.services.naming import (
    _safe_segment,
    render_filename,
    template_has_unique_token,
    validate_template,
)


class _ArtistRef:
    def __init__(self, name: str):
        self.name = name


class _LiveSetArtistRef:
    def __init__(self, artist_name: str):
        self.artist = _ArtistRef(artist_name)


class _PartyRef:
    def __init__(self, name: str, series_name: str | None = None):
        self.name = name
        self.series = _ArtistRef(series_name) if series_name else None


class _VenueRef:
    def __init__(self, name: str):
        self.name = name


class _Live:
    """Stand-in matching the fields render_filename touches."""

    def __init__(
        self, *,
        slug: str = "test-set",
        set_type: str = "headline",
        date_val: date | None = date(2026, 1, 15),
        party_name: str | None = "Awakenings",
        series_name: str | None = "Essential Mix",
        venue_name: str | None = "Spaarnwoude",
        artists: list[str] | None = None,
    ):
        self.id = uuid.UUID("00000000-0000-0000-0000-00000000abcd")
        self.slug = slug
        self.set_type = set_type
        self.date = date_val
        self.party = _PartyRef(party_name, series_name) if party_name else None
        self.venue = _VenueRef(venue_name) if venue_name else None
        if artists is None:
            artists = ["Carl Cox"]
        self.artists = [_LiveSetArtistRef(name) for name in artists]


def test_safe_segment_normalises():
    assert _safe_segment("Carl Cox") == "Carl-Cox"
    assert _safe_segment("Awakenings/2026") == "Awakenings-2026"
    # Leading / trailing dots stripped, runs of dots collapsed (no `..` allowed)
    assert _safe_segment("...weird..name..") == "weird.name"
    assert _safe_segment("hello world") == "hello-world"
    assert _safe_segment("") == ""
    # Path-traversal sentinel never survives
    assert ".." not in _safe_segment(".." * 5)


def test_render_filename_full_template():
    """Literal characters between tokens (' - ' here) survive unchanged into
    the output; only token VALUES get safe-segment normalised."""
    live = _Live()
    out = render_filename(
        "{Artist}/{Year}/{Date} - {Party} - {Slug}{Ext}",
        live,
        ext=".opus",
    )
    assert out == "Carl-Cox/2026/2026-01-15 - Awakenings - test-set.opus"


def test_render_filename_setid_only():
    live = _Live()
    out = render_filename("originals/{SetId}{Ext}", live, ext=".flac")
    assert out == "originals/00000000-0000-0000-0000-00000000abcd.flac"


def test_render_filename_missing_party_renders_empty():
    """A template with {Party} on a set with no party leaves an empty segment.
    Resulting collapsed-slash means callers should pick templates with
    required tokens."""
    live = _Live(party_name=None)
    out = render_filename("{Artist}/{Party}/{Slug}{Ext}", live, ext=".opus")
    # The empty {Party} produces double-slash that gets collapsed.
    assert out == "Carl-Cox/test-set.opus"


def test_render_filename_no_date_year_is_empty():
    live = _Live(date_val=None)
    out = render_filename("{Year}/{Slug}{Ext}", live, ext=".opus")
    assert out == "test-set.opus"


def test_render_filename_unknown_token_renders_empty():
    live = _Live()
    out = render_filename("{NotAToken}/{Slug}{Ext}", live, ext=".opus")
    assert out == "test-set.opus"


def test_render_filename_backslash_normalised():
    live = _Live()
    out = render_filename(
        r"{Artist}\{Slug}{Ext}", live, ext=".opus",
    )
    assert "\\" not in out
    assert out == "Carl-Cox/test-set.opus"


def test_render_filename_normalises_repeated_slashes():
    live = _Live()
    out = render_filename(
        "{Artist}//{Slug}{Ext}", live, ext=".opus",
    )
    assert out == "Carl-Cox/test-set.opus"


def test_render_filename_no_artists_yet():
    live = _Live(artists=[])
    out = render_filename("{Artist}/{Slug}{Ext}", live, ext=".opus")
    # Empty Artist segment collapses
    assert out == "test-set.opus"


def test_validate_template_errors():
    for bad in ("{Nope}.{Ext}", "{Slug}", "../{Slug}.{Ext}", "/abs/{Slug}.{Ext}",
                "C:/x/{Slug}.{Ext}", "C:{Slug}.{Ext}", "\\\\server\\{Slug}.{Ext}"):
        assert validate_template(bad), bad
    assert validate_template("{Artist}/{Date} {Slug}.{Ext}") == []
    assert validate_template("originals/{SetId}{Ext}") == []


def test_validate_template_names_the_unknown_token():
    errors = validate_template("{Nope}/{Slug}{Ext}")
    assert any("{Nope}" in e for e in errors)


def test_template_has_unique_token():
    assert template_has_unique_token("{Artist}/{Slug}.{Ext}")
    assert template_has_unique_token("{SetId}{Ext}")
    assert not template_has_unique_token("{Artist}/{Date}.{Ext}")


def test_render_filename_dot_before_ext_is_not_doubled():
    """{Ext} carries its leading dot, so "{Slug}.{Ext}" and "{Slug}{Ext}"
    render the same file name."""
    live = _Live()
    assert render_filename("{Artist}/{Slug}.{Ext}", live, ext=".opus") == "Carl-Cox/test-set.opus"
    assert render_filename("{Artist}/{Slug}{Ext}", live, ext=".opus") == "Carl-Cox/test-set.opus"
