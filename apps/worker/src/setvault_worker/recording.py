"""Record every background job run in the ``jobs`` table (Admin -> Jobs).

``RecordingWorker`` is an ``rq.Worker`` whose start/success/failure hooks write
one ``Job`` row per run (RQ reuses ids, so the row has its own UUID and keeps
the RQ id in ``rq_id``). The started hook inserts the row and stores its id in
``job.meta["setvault_job_row"]``; the success/failure hooks update it.

Recording is best effort: it must never fail or hold up a job. Every write is
wrapped in try/except (logged), uses its own short-lived NullPool engine with
tight timeouts, and never touches ``setvault_core.db``'s shared engine (the
job bodies' ``run_job`` disposes that one).
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from rq import Worker
from setvault_core.models.identity import User
from setvault_core.models.system import Job
from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from sqlalchemy.pool import NullPool

logger = logging.getLogger(__name__)

ROW_META_KEY = "setvault_job_row"
REDACTED = "[redacted]"

# Frequent periodic jobs: recorded only when they fail (row written lazily
# then), so their 5-minute cadence doesn't flood the table. Spelled as
# short_kind() of the real func paths: media-root health checks, monitor
# dispatch, monitor polls (enqueued by the dispatch) and the tus-spool prune.
QUIET_KINDS: frozenset[str] = frozenset({
    "media_root_health.run_health_checks_sync",
    "monitor_dispatch.run_dispatch_monitors",
    "monitor_poll.run_poll_monitor",
    "tus_spool_prune.run_prune_tus_spool",
})

# A key is redacted when one of its *words* is a sensitive word, optionally
# plural. Words are split on non-alphanumerics (so snake_case and kebab-case)
# and camelCase humps, compared case-insensitively. Matching whole words keeps
# `to` from hitting `total`/`photo`/`stop` and `token` from hitting `tokenize`,
# while `recipient_email`, `reset_link`, `webhookUrl`, `access_token`, `emails`
# and `addresses` are all caught.
_SENSITIVE_WORD = re.compile(
    r"(?:email|to|address|link|url|token|password|secret)(?:e?s)?", re.IGNORECASE
)
_CAMEL_HUMP = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_NON_ALNUM = re.compile(r"[^A-Za-z0-9]+")

_CONNECT_TIMEOUT_S = 5
_WRITE_TIMEOUT_S = 10


def short_kind(func_name: str) -> str:
    """``setvault_core.jobs.email.send_email_job`` -> ``email.send_email_job``."""
    return ".".join(func_name.split(".")[-2:])


def _is_sensitive_key(key: object) -> bool:
    words = _NON_ALNUM.split(_CAMEL_HUMP.sub("_", str(key)))
    return any(_SENSITIVE_WORD.fullmatch(w) for w in words if w)


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return redact(value)
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(v) for v in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def redact(kwargs: dict) -> dict:
    """JSON-safe copy of ``kwargs`` with sensitive values (recursively) replaced."""
    return {
        str(k): REDACTED if _is_sensitive_key(k) else _json_safe(v)
        for k, v in kwargs.items()
    }


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def _last_line(exc_string: str) -> str | None:
    lines = [ln.strip() for ln in (exc_string or "").splitlines() if ln.strip()]
    return lines[-1] if lines else None


def _initiator_candidate(kwargs: dict) -> uuid.UUID | None:
    for key in ("actor_user_id", "user_id"):
        raw = kwargs.get(key)
        if isinstance(raw, uuid.UUID):
            return raw
        if isinstance(raw, str):
            try:
                return uuid.UUID(raw)
            except ValueError:
                continue
    return None


class JobRecorder:
    """Writes ``jobs`` rows through a throwaway engine per write."""

    def __init__(self, database_url: str | None):
        self.database_url = database_url

    def _run(self, fn) -> Any:
        if not self.database_url:
            raise RuntimeError("DATABASE_URL not set; job runs are not recorded")

        async def _main():
            engine = create_async_engine(
                self.database_url, poolclass=NullPool,
                connect_args={"timeout": _CONNECT_TIMEOUT_S,
                              "command_timeout": _CONNECT_TIMEOUT_S},
            )
            try:
                async with engine.begin() as conn:
                    return await fn(conn)
            finally:
                await engine.dispose()

        async def _bounded():
            return await asyncio.wait_for(_main(), _WRITE_TIMEOUT_S)

        return asyncio.run(_bounded())

    @staticmethod
    def _base_values(job) -> dict:
        kwargs = dict(getattr(job, "kwargs", None) or {})
        return {
            "rq_id": str(job.id)[:64],
            "kind": short_kind(job.func_name or "")[:64],
            "payload": redact(kwargs),
            "progress_pct": 0,
            "result": {},
        }

    @staticmethod
    async def _initiated_by(conn: AsyncConnection, job) -> uuid.UUID | None:
        candidate = _initiator_candidate(dict(getattr(job, "kwargs", None) or {}))
        if candidate is None:
            return None
        found = await conn.execute(select(User.id).where(User.id == candidate))
        return found.scalar_one_or_none()

    def started(self, job) -> str:
        row_id = str(uuid.uuid4())

        async def _write(conn: AsyncConnection):
            values = self._base_values(job)
            values.update(id=row_id, status="started", started_at=_now(),
                          initiated_by=await self._initiated_by(conn, job))
            await conn.execute(insert(Job).values(**values))

        self._run(_write)
        return row_id

    def ended(self, job, row_id: str | None, *, status: str,
              message: str | None, result: dict | None) -> None:
        finished_at = _now()
        end = {"status": status, "message": message, "finished_at": finished_at}
        if result is not None:
            end["result"] = _json_safe(result)

        async def _write(conn: AsyncConnection):
            if row_id is not None:
                done = await conn.execute(
                    update(Job).where(Job.id == row_id).values(**end)
                )
                if done.rowcount:
                    return
            # No started row (quiet kind, or the main worker process handling
            # a crashed work horse): write the whole row now.
            values = self._base_values(job)
            values.update(end)
            values.update(
                id=row_id or str(uuid.uuid4()),
                started_at=_aware(getattr(job, "started_at", None)) or finished_at,
                initiated_by=await self._initiated_by(conn, job),
            )
            await conn.execute(insert(Job).values(**values))

        self._run(_write)


class RecordingWorker(Worker):
    """``rq.Worker`` that records each job run for Admin -> Jobs."""

    def __init__(self, *args, database_url: str | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.recorder = JobRecorder(database_url or os.environ.get("DATABASE_URL"))

    @staticmethod
    def _quiet(job) -> bool:
        try:  # func_name deserializes the job data; never let that escape
            return short_kind(getattr(job, "func_name", None) or "") in QUIET_KINDS
        except Exception:
            return False

    @staticmethod
    def _row_id(job) -> str | None:
        row_id = (getattr(job, "meta", None) or {}).get(ROW_META_KEY)
        if row_id is None:
            try:  # the main process's copy may predate the horse's save_meta
                row_id = (job.get_meta(refresh=True) or {}).get(ROW_META_KEY)
            except Exception:
                logger.debug("job recording: could not refresh meta of %s", job.id,
                             exc_info=True)
        return row_id

    def prepare_job_execution(self, job, *args, **kwargs):
        super().prepare_job_execution(job, *args, **kwargs)
        if self._quiet(job):
            return
        try:
            row_id = self.recorder.started(job)
        except Exception:
            logger.warning("job recording: could not record start of %s", job.id,
                           exc_info=True)
            return
        try:
            job.meta[ROW_META_KEY] = row_id
            job.save_meta()
        except Exception:
            logger.warning("job recording: could not save row id on %s", job.id,
                           exc_info=True)

    def handle_job_success(self, job, queue, started_job_registry):
        if not self._quiet(job):
            try:
                result = getattr(job, "_result", None)
                self.recorder.ended(
                    job, self._row_id(job), status="finished", message=None,
                    result=result if isinstance(result, dict) else None,
                )
            except Exception:
                logger.warning("job recording: could not record success of %s", job.id,
                               exc_info=True)
        return super().handle_job_success(job, queue, started_job_registry)

    def handle_job_failure(self, job, queue, started_job_registry=None, exc_string=""):
        try:
            row_id = None if self._quiet(job) else self._row_id(job)
            self.recorder.ended(job, row_id, status="failed",
                                message=_last_line(exc_string), result=None)
        except Exception:
            logger.warning("job recording: could not record failure of %s", job.id,
                           exc_info=True)
        return super().handle_job_failure(
            job, queue, started_job_registry=started_job_registry, exc_string=exc_string,
        )
