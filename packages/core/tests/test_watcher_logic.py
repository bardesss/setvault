"""Unit tests for the watchdog event handler.

The full ``run_watcher`` loop is integration-level (needs Redis + a real
filesystem observer + a Postgres-backed WatchFolder set). The pieces that
are pure logic — audio-file filtering and event-to-enqueue translation —
are tested here.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

from setvault_core.services.watcher import (
    _is_audio_file,
    _is_hidden,
    _PendingFiles,
    _WatchFolderHandler,
)


def test_audio_file_filter():
    assert _is_audio_file("/x/y/file.opus") is True
    assert _is_audio_file("/x/file.FLAC") is True   # case-insensitive
    assert _is_audio_file("/x/file.mp3") is True
    assert _is_audio_file("/x/readme.txt") is False
    assert _is_audio_file("/x/no_ext") is False
    assert _is_audio_file("/x/file.opus.tmp") is False  # not audio


def test_created_event_enqueues_audio_file():
    wf_id = uuid.uuid4()
    enqueue = MagicMock()
    handler = _WatchFolderHandler(watch_folder_id=wf_id, enqueue=enqueue)

    evt = MagicMock(spec=[])
    evt.is_directory = False
    evt.src_path = "/srv/incoming/track.flac"
    handler.on_created(evt)

    enqueue.assert_called_once_with(wf_id, "/srv/incoming/track.flac")


def test_created_event_skips_directories():
    enqueue = MagicMock()
    handler = _WatchFolderHandler(watch_folder_id=uuid.uuid4(), enqueue=enqueue)

    evt = MagicMock(spec=[])
    evt.is_directory = True
    evt.src_path = "/srv/incoming/subdir"
    handler.on_created(evt)

    enqueue.assert_not_called()


def test_created_event_skips_non_audio():
    enqueue = MagicMock()
    handler = _WatchFolderHandler(watch_folder_id=uuid.uuid4(), enqueue=enqueue)

    evt = MagicMock(spec=[])
    evt.is_directory = False
    evt.src_path = "/srv/incoming/notes.txt"
    handler.on_created(evt)

    enqueue.assert_not_called()


def test_moved_event_uses_dest_path():
    """A file MOVED INTO the watched tree should enqueue against its new path."""
    wf_id = uuid.uuid4()
    enqueue = MagicMock()
    handler = _WatchFolderHandler(watch_folder_id=wf_id, enqueue=enqueue)

    evt = MagicMock(spec=[])
    evt.is_directory = False
    evt.dest_path = "/srv/incoming/moved.opus"
    handler.on_moved(evt)

    enqueue.assert_called_once_with(wf_id, "/srv/incoming/moved.opus")


def test_discarded_and_hidden_paths_are_ignored():
    """Resolving an Unmatched file as 'discard' moves it into
    <watch folder>/.discarded/, which is inside the watched tree. That move
    must not be picked up as a fresh arrival (it would land straight back
    in the inbox)."""
    root = "/srv/incoming"
    enqueue = MagicMock()
    handler = _WatchFolderHandler(watch_folder_id=uuid.uuid4(), enqueue=enqueue, root=root)

    for dest in (
        "/srv/incoming/.discarded/bad name.flac",
        "/srv/incoming/sub/.partial.flac",  # rsync / Syncthing temp style
    ):
        evt = MagicMock(spec=[])
        evt.is_directory = False
        evt.dest_path = dest
        handler.on_moved(evt)

    enqueue.assert_not_called()


def test_hidden_check_only_looks_below_the_root():
    """A dot-directory ABOVE the watch folder must not hide everything in it."""
    assert _is_hidden("/home/u/.local/watch/set.flac", "/home/u/.local/watch") is False
    assert _is_hidden("/home/u/.local/watch/.discarded/set.flac", "/home/u/.local/watch") is True


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _stat_from(sizes: dict[str, int]):
    def _stat(path: str):
        if path not in sizes:
            raise FileNotFoundError(path)
        return SimpleNamespace(st_size=sizes[path], st_mtime_ns=sizes[path])
    return _stat


def test_pending_file_waits_until_writes_stop():
    """A file still being copied in (size growing) is not handed off; once it
    has been unchanged for the settle window it is, exactly once."""
    clock = _Clock()
    sizes = {"/w/set.flac": 100}
    pending = _PendingFiles(settle_seconds=10, clock=clock, stat=_stat_from(sizes))
    wf_id = uuid.uuid4()

    pending.add(wf_id, "/w/set.flac")
    assert pending.pop_settled() == []           # first observation

    for _ in range(5):                           # copy keeps growing
        clock.now += 4
        sizes["/w/set.flac"] += 1_000
        assert pending.pop_settled() == []

    clock.now += 4                               # size stable, window not elapsed
    assert pending.pop_settled() == []
    clock.now += 7                               # stable for 11s
    assert pending.pop_settled() == [(wf_id, "/w/set.flac")]
    clock.now += 20
    assert pending.pop_settled() == []           # handed off once


def test_pending_file_that_vanishes_or_stays_empty_is_dropped():
    clock = _Clock()
    sizes = {"/w/empty.flac": 0, "/w/gone.flac": 5}
    pending = _PendingFiles(settle_seconds=10, clock=clock, stat=_stat_from(sizes))
    pending.add(uuid.uuid4(), "/w/empty.flac")
    pending.add(uuid.uuid4(), "/w/gone.flac")

    pending.pop_settled()
    del sizes["/w/gone.flac"]
    clock.now += 11
    assert pending.pop_settled() == []
    clock.now += 11
    assert pending.pop_settled() == []
