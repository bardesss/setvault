"""Filesystem watcher service.

Subscribes to ``created`` / ``moved`` events under every enabled
``WatchFolder.host_path`` and enqueues a ``watch_folder_ingest`` RQ job for
each audio file. Designed to run as a long-lived process, launched via
``python -m setvault_core.services.watcher`` (in the bundled image it runs as
its own s6-overlay longrun alongside uvicorn and the RQ worker).

Re-syncs the active set of watched paths every ``RECONCILE_INTERVAL_SECONDS``
(default 30) so admin-side enable/disable + path changes pick up without
restarting the watcher.
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from collections.abc import Iterable
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from setvault_core.db import init_engine, run_job, session_factory
from setvault_core.models.watch_folder import WatchFolder

logger = logging.getLogger(__name__)

RECONCILE_INTERVAL_SECONDS = 30

# Audio extensions the pipeline accepts. Lowercase, with leading dot.
_AUDIO_EXTENSIONS = frozenset({
    ".mp3", ".flac", ".wav", ".aac", ".m4a", ".opus", ".ogg", ".aif", ".aiff",
})


def _is_audio_file(path: str) -> bool:
    return Path(path).suffix.lower() in _AUDIO_EXTENSIONS


class _WatchFolderHandler(FileSystemEventHandler):
    """Translates watchdog events into RQ job enqueues for one WatchFolder."""

    def __init__(self, *, watch_folder_id: uuid.UUID, enqueue: callable) -> None:
        self._watch_folder_id = watch_folder_id
        self._enqueue = enqueue

    def on_created(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        if not _is_audio_file(event.src_path):
            return
        self._enqueue(self._watch_folder_id, event.src_path)

    def on_moved(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        # Files moved INTO the watched tree should also be treated as fresh
        # arrivals. event.dest_path is the new location.
        dest = getattr(event, "dest_path", None)
        if not dest or not _is_audio_file(dest):
            return
        self._enqueue(self._watch_folder_id, dest)


def _make_enqueue_callable():
    """Build the actual enqueue function. Imported here so unit tests can
    monkeypatch the queue or substitute a synchronous fake."""
    import os as _os

    from redis import Redis
    from rq import Queue

    redis_url = _os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    queue = Queue("default", connection=Redis.from_url(redis_url))

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
) -> None:
    """Synchronise the observer's schedule with the current set of enabled
    watch folders. Schedules new ones, unschedules ones that vanished."""
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
        handler = _WatchFolderHandler(watch_folder_id=wf_id, enqueue=enqueue)
        watch = observer.schedule(handler, host_path, recursive=True)
        active_paths[wf_id] = (host_path, watch)
        logger.info("watching %s -> %s", wf_id, host_path)


async def run_watcher(
    *,
    enqueue: callable | None = None,
    reconcile_interval: int = RECONCILE_INTERVAL_SECONDS,
) -> None:
    """Run the watcher until cancelled.

    Parameters
    ----------
    enqueue
        Optional injection for tests. Default builds an RQ enqueue against
        REDIS_URL.
    reconcile_interval
        Seconds between DB re-reads of the enabled WatchFolder set.
    """
    if enqueue is None:
        enqueue = _make_enqueue_callable()

    if "DATABASE_URL" in os.environ:
        init_engine(os.environ["DATABASE_URL"])

    observer = Observer()
    observer.start()
    active: dict[uuid.UUID, tuple[str, object]] = {}

    try:
        while True:
            async with session_factory()() as s:
                rows = await _load_active_watch_folders(s)
            _reconcile_observers(observer, active, rows, enqueue)
            await asyncio.sleep(reconcile_interval)
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
