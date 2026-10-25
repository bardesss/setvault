"""Filesystem watcher service.

Subscribes to ``created`` / ``moved`` events under every enabled
``WatchFolder.host_path`` and enqueues a ``watch_folder_ingest`` RQ job for
each audio file. Designed to run as a long-lived process, launched via
``python -m setvault_core.services.watcher`` (in the bundled image it runs as
its own s6-overlay longrun alongside uvicorn and the RQ worker).

Re-syncs the active set of watched paths every ``RECONCILE_INTERVAL_SECONDS``
(default 30) so admin-side enable/disable + path changes pick up without
restarting the watcher.

Events don't go straight to the queue: ``created`` fires as soon as a writer
opens the file, long before a ``cp`` or SMB copy has finished. Arrivals wait
in ``_PendingFiles`` until their size and mtime stop changing for
``SETTLE_SECONDS``.

Events only fire while the watcher is running, so when it (re)subscribes a
folder it also scans for files that arrived after the folder's
``last_watched_at`` heartbeat (or everything, for a folder never watched)
and feeds them through the same settle tracker.
"""
from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from setvault_core.config import redis_url
from setvault_core.db import init_engine, run_job, session_factory
from setvault_core.models.catalog import LiveSet
from setvault_core.models.watch_folder import UnmatchedFile, WatchFolder

logger = logging.getLogger(__name__)

RECONCILE_INTERVAL_SECONDS = 30
SETTLE_SECONDS = 10
SETTLE_POLL_SECONDS = 2

# Audio extensions the pipeline accepts. Lowercase, with leading dot.
_AUDIO_EXTENSIONS = frozenset({
    ".mp3", ".flac", ".wav", ".aac", ".m4a", ".opus", ".ogg", ".aif", ".aiff",
})


def _is_audio_file(path: str) -> bool:
    return Path(path).suffix.lower() in _AUDIO_EXTENSIONS


def _is_hidden(path: str, root: str | None) -> bool:
    """True if any component below ``root`` starts with a dot: the Unmatched
    inbox's ``.discarded/`` dir, plus rsync / Syncthing temp files. Without a
    root only the filename is checked."""
    p = Path(path)
    parts: tuple[str, ...] = (p.name,)
    if root is not None:
        try:
            parts = p.relative_to(root).parts
        except ValueError:
            pass
    return any(part.startswith(".") for part in parts)


class _WatchFolderHandler(FileSystemEventHandler):
    """Translates watchdog events into ingest candidates for one WatchFolder."""

    def __init__(
        self, *, watch_folder_id: uuid.UUID, enqueue: callable, root: str | None = None,
    ) -> None:
        self._watch_folder_id = watch_folder_id
        self._enqueue = enqueue
        self._root = root

    def _wanted(self, path: str) -> bool:
        return _is_audio_file(path) and not _is_hidden(path, self._root)

    def on_created(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        if not self._wanted(event.src_path):
            return
        self._enqueue(self._watch_folder_id, event.src_path)

    def on_moved(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        # Files moved INTO the watched tree should also be treated as fresh
        # arrivals. event.dest_path is the new location.
        dest = getattr(event, "dest_path", None)
        if not dest or not self._wanted(dest):
            return
        self._enqueue(self._watch_folder_id, dest)


class _PendingFiles:
    """Arrivals waiting for their writer to finish.

    ``add`` is called from watchdog's observer thread; ``pop_settled`` from
    the watcher loop. A file is settled once its (size, mtime) has been
    unchanged for ``settle_seconds``. Files that vanish are dropped, and so
    are empty files once settled (nothing to ingest).
    """

    def __init__(
        self,
        *,
        settle_seconds: float = SETTLE_SECONDS,
        clock: callable = time.monotonic,
        stat: callable = os.stat,
    ) -> None:
        self._settle_seconds = settle_seconds
        self._clock = clock
        self._stat = stat
        self._lock = threading.Lock()
        # path -> (watch_folder_id, last (size, mtime_ns) or None, unchanged since)
        self._files: dict[str, tuple[uuid.UUID, tuple[int, int] | None, float]] = {}

    def add(self, watch_folder_id: uuid.UUID, path: str) -> None:
        with self._lock:
            self._files[path] = (watch_folder_id, None, self._clock())

    def pop_settled(self) -> list[tuple[uuid.UUID, str]]:
        now = self._clock()
        settled: list[tuple[uuid.UUID, str]] = []
        with self._lock:
            for path, (wf_id, last, since) in list(self._files.items()):
                try:
                    st = self._stat(path)
                except OSError:
                    del self._files[path]
                    continue
                current = (st.st_size, st.st_mtime_ns)
                if current != last:
                    self._files[path] = (wf_id, current, now)
                    continue
                if now - since < self._settle_seconds:
                    continue
                del self._files[path]
                if st.st_size > 0:
                    settled.append((wf_id, path))
        return settled


def _make_enqueue_callable():
    """Build the actual enqueue function. Imported here so unit tests can
    monkeypatch the queue or substitute a synchronous fake."""

    from redis import Redis
    from rq import Queue

    queue = Queue("default", connection=Redis.from_url(redis_url()))

    def _enqueue(watch_folder_id: uuid.UUID, file_path: str) -> None:
        # Suspended files (.tmp suffix, in-flight copies) get skipped; the
        # watcher will see the final rename event when the writer completes.
        if file_path.endswith(".tmp"):
            return
        queue.enqueue(
            "setvault_core.jobs.watch_folder_ingest.run_watch_folder_ingest",
            watch_folder_id=str(watch_folder_id),
            file_path=file_path,
        )

    return _enqueue


async def _load_active_watch_folders(session: AsyncSession) -> list[WatchFolder]:
    return list((await session.execute(
        select(WatchFolder).where(WatchFolder.enabled.is_(True))
    )).scalars().all())


def _reconcile_observers(
    observer: Observer,
    active_paths: dict[uuid.UUID, tuple[str, object]],
    rows: Iterable[WatchFolder],
    enqueue: callable,
) -> list[uuid.UUID]:
    """Synchronise the observer's schedule with the current set of enabled
    watch folders. Schedules new ones, unschedules ones that vanished.
    Returns the ids of the folders newly scheduled by this call."""
    scheduled: list[uuid.UUID] = []
    desired = {row.id: row.host_path for row in rows}

    # Unschedule any path that's no longer desired.
    for wf_id in list(active_paths.keys()):
        if wf_id not in desired:
            _path, watch = active_paths.pop(wf_id)
            try:
                observer.unschedule(watch)
            except (KeyError, RuntimeError):
                pass

    # Schedule each newly desired path. Skip if path doesn't exist (admin
    # may have configured a typo or a temporarily unmounted share).
    for wf_id, host_path in desired.items():
        if wf_id in active_paths:
            continue
        if not os.path.isdir(host_path):
            logger.warning("watch folder %s path missing: %s", wf_id, host_path)
            continue
        handler = _WatchFolderHandler(watch_folder_id=wf_id, enqueue=enqueue, root=host_path)
        watch = observer.schedule(handler, host_path, recursive=True)
        active_paths[wf_id] = (host_path, watch)
        scheduled.append(wf_id)
        logger.info("watching %s -> %s", wf_id, host_path)
    return scheduled


# Slack on the heartbeat comparison: a file that landed in the last moments
# before the watcher went down may not have fired an event either.
_CATCH_UP_SLACK_SECONDS = 60


def _catch_up_candidates(root: str, *, since: float | None, known: set[str]) -> list[str]:
    """Audio files under ``root`` the watcher may have missed while it wasn't
    observing: everything when ``since`` is None (a never-watched folder),
    otherwise files written or moved in after ``since`` (epoch seconds).
    Hidden dirs/files and paths in ``known`` are skipped. ctime is included
    because a copy that preserves mtime (``cp -p``, ``rsync -a``) still gets
    a fresh ctime when it lands."""
    found: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in filenames:
            if name.startswith(".") or not _is_audio_file(name):
                continue
            path = os.path.join(dirpath, name)
            if path in known:
                continue
            if since is not None:
                try:
                    st = os.stat(path)
                except OSError:
                    continue
                if max(st.st_mtime, st.st_ctime) < since - _CATCH_UP_SLACK_SECONDS:
                    continue
            found.append(path)
    return found


async def _known_paths(session: AsyncSession, watch_folder_id: uuid.UUID) -> set[str]:
    """Source paths the ingest job has already handled for this folder: sets
    it created (source_url holds the source path) and Unmatched rows."""
    sets = (await session.execute(
        select(LiveSet.source_url).where(LiveSet.source_type == "watch_folder"),
    )).scalars().all()
    unmatched = (await session.execute(
        select(UnmatchedFile.file_path).where(UnmatchedFile.watch_folder_id == watch_folder_id),
    )).scalars().all()
    return {p for p in (*sets, *unmatched) if p}


async def _catch_up(
    session: AsyncSession, row: WatchFolder, add: callable,
) -> int:
    """Queue (via the settle tracker) files that arrived while ``row`` wasn't
    being watched. Returns how many were queued."""
    since = row.last_watched_at.timestamp() if row.last_watched_at else None
    known = await _known_paths(session, row.id)
    found = await asyncio.to_thread(
        _catch_up_candidates, row.host_path, since=since, known=known,
    )
    for path in found:
        add(row.id, path)
    if found:
        logger.info("watch folder %s: catching up on %d file(s)", row.id, len(found))
    return len(found)


async def _heartbeat(session: AsyncSession, watch_folder_ids: Iterable[uuid.UUID]) -> None:
    ids = list(watch_folder_ids)
    if not ids:
        return
    await session.execute(
        update(WatchFolder).where(WatchFolder.id.in_(ids))
        .values(last_watched_at=datetime.now(UTC)),
    )
    await session.commit()


async def run_watcher(
    *,
    enqueue: callable | None = None,
    reconcile_interval: int = RECONCILE_INTERVAL_SECONDS,
    settle_poll: float = SETTLE_POLL_SECONDS,
) -> None:
    """Run the watcher until cancelled.

    Parameters
    ----------
    enqueue
        Optional injection for tests. Default builds an RQ enqueue against
        REDIS_URL.
    reconcile_interval
        Seconds between DB re-reads of the enabled WatchFolder set.
    settle_poll
        Seconds between checks of pending arrivals for a finished write.
    """
    if enqueue is None:
        enqueue = _make_enqueue_callable()

    if "DATABASE_URL" in os.environ:
        init_engine(os.environ["DATABASE_URL"])

    observer = Observer()
    observer.start()
    active: dict[uuid.UUID, tuple[str, object]] = {}
    pending = _PendingFiles()
    next_reconcile = 0.0

    try:
        while True:
            if time.monotonic() >= next_reconcile:
                async with session_factory()() as s:
                    rows = await _load_active_watch_folders(s)
                    scheduled = set(_reconcile_observers(observer, active, rows, pending.add))
                    # Catch up first (it reads the previous heartbeat), then
                    # stamp every observed folder as watched up to now.
                    for row in rows:
                        if row.id in scheduled:
                            await _catch_up(s, row, pending.add)
                    await _heartbeat(s, active.keys())
                next_reconcile = time.monotonic() + reconcile_interval
            for wf_id, path in pending.pop_settled():
                enqueue(wf_id, path)
            await asyncio.sleep(settle_poll)
    finally:
        observer.stop()
        observer.join(timeout=5)


def main() -> None:
    """Entry point used by the compose service / worker container."""
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    run_job(run_watcher())


if __name__ == "__main__":
    main()
