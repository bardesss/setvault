"""Tests for the filename-parser inside watch_folder_ingest.

End-to-end ingest behavior (probe → place → pipeline → unmatched-fallback)
is integration territory and gets covered by the apps/web API + Playwright
tests in 5C. The filename parser is pure logic and worth a dedicated unit
sweep.
"""
from __future__ import annotations

from datetime import date

import pytest
from setvault_core.jobs.watch_folder_ingest import _parse_filename


@pytest.mark.parametrize(("stem", "expected"), [
    # Explicit date + artist + title
    (
        "2026-01-15 - Carl Cox - Awakenings Closing Set",
        {"date": date(2026, 1, 15), "artist": "Carl Cox", "title": "Awakenings Closing Set"},
    ),
    # Alt-date format (dots) and no dash before artist
    (
        "2026.01.15 Carl Cox - Awakenings",
        {"date": date(2026, 1, 15), "artist": "Carl Cox", "title": "Awakenings"},
    ),
    # No date — fall through to bare artist - title
    (
        "Carl Cox - Awakenings Closing Set",
        {"artist": "Carl Cox", "title": "Awakenings Closing Set"},
    ),
    # Em-dash separator (U+2013 — the parser matches both ASCII - and Unicode -)
    (
        "Carl Cox – Awakenings",  # noqa: RUF001
        {"artist": "Carl Cox", "title": "Awakenings"},
    ),
    # Excess whitespace
    (
        "  Carl Cox  -  Awakenings  ",
        {"artist": "Carl Cox", "title": "Awakenings"},
    ),
])
def test_parse_filename_known_patterns(stem: str, expected: dict):
    result = _parse_filename(stem)
    assert result is not None, f"expected a parse for {stem!r}"
    for k, v in expected.items():
        assert result.get(k) == v, f"key {k}: got {result.get(k)!r}, want {v!r}"


@pytest.mark.parametrize("stem", [
    # The parser intentionally treats ANY dashed string as artist-title
    # (admin fixes the metadata on the resulting draft). These cases lack
    # both a date prefix AND any dash, so they fall through to None and
    # land in the unmatched inbox.
    "no_separator_at_all",
    "noseparatoratall",
    "",
    "   ",
    "OnlyOneName",
])
def test_parse_filename_no_pattern(stem: str):
    assert _parse_filename(stem) is None


def test_parse_filename_invalid_date_falls_back():
    """A date-shaped prefix with an impossible date (month 13) should still
    parse via the no-date pattern."""
    stem = "2026-13-99 - Carl Cox - Awakenings"
    result = _parse_filename(stem)
    # The third no-date pattern matches whatever's after the bad-date prefix.
    # Artist token becomes everything before the LAST dash.
    assert result is not None
    assert result.get("title") == "Awakenings"
    # Date must NOT be set when the prefix was invalid
    assert "date" not in result


async def _attribution_fixture(session, tmp_path, *, creator_disabled=False):
    import uuid
    from datetime import UTC, datetime

    from setvault_core.models.catalog import MediaRoot
    from setvault_core.models.identity import User
    from setvault_core.models.watch_folder import WatchFolder

    def _admin(tag):
        return User(email=f"{tag}-{uuid.uuid4().hex[:6]}@x.test",
                    username=f"{tag}{uuid.uuid4().hex[:6]}", display_name=tag,
                    password_hash="x", role="admin")

    first, creator = _admin("first"), _admin("creator")
    session.add(first)
    await session.flush()  # first admin by created_at
    if creator_disabled:
        creator.disabled_at = datetime.now(UTC)
    session.add(creator)
    root = MediaRoot(name=f"r-{uuid.uuid4().hex[:6]}", host_path=str(tmp_path / "media"))
    session.add(root)
    await session.flush()
    wf = WatchFolder(name="wf", host_path=str(tmp_path / f"watch-{uuid.uuid4().hex[:6]}"),
                     target_media_root_id=root.id, created_by=creator.id)
    session.add(wf)
    await session.flush()
    return wf, first, creator


async def test_ingest_is_attributed_to_the_folder_creator(session, tmp_path):
    from setvault_core.jobs.watch_folder_ingest import _ingest_actor

    wf, _first, creator = await _attribution_fixture(session, tmp_path)
    assert (await _ingest_actor(session, wf)).id == creator.id


async def test_ingest_falls_back_to_an_active_admin(session, tmp_path):
    from setvault_core.jobs.watch_folder_ingest import _ingest_actor

    wf, _first, creator = await _attribution_fixture(session, tmp_path, creator_disabled=True)
    actor = await _ingest_actor(session, wf)
    assert actor.id != creator.id
    assert actor.role == "admin" and actor.disabled_at is None

    wf.created_by = None  # folders created before the column existed
    actor = await _ingest_actor(session, wf)
    assert actor.role == "admin" and actor.disabled_at is None
