"""Boot-time repair of legacy ``/srv`` paths stored in the DB.

Old images forced ``SETVAULT_MEDIA_PATH=/srv/media`` even in bundled mode, so
existing bundled installs persist ``/srv/media`` (and watch folders under
``/srv/watch``) in their database. Bundled mode now keeps data under ``/data``;
this job repoints those rows so ingest keeps working.

Idempotent and conservative: only runs in bundled mode, only rewrites values
equal to the legacy prefix or strictly below it (``/srv/media2`` is untouched),
and does nothing when the effective path equals the legacy one.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_core.db import init_engine, run_job, session_factory
from setvault_core.jobs.email import DATABASE_URL_ENV
from setvault_core.models.catalog import LiveSet, MediaRoot
from setvault_core.services.audit import log as audit_log

LEGACY_PAIRS: tuple[tuple[str, str], ...] = (
    ("/srv/media", "SETVAULT_MEDIA_PATH"),
    ("/srv/watch", "SETVAULT_WATCH_FOLDERS_PATH"),
)

# (table, column) targets per legacy prefix.
_TARGETS: dict[str, tuple[tuple[str, str], ...]] = {
    "/srv/media": (("media_roots", "host_path"),),
    "/srv/watch": (
        ("watch_folders", "host_path"),
        ("unmatched_files", "file_path"),
        ("live_sets", "source_url"),
    ),
}

_BATCH = 500


def rewrite_prefix(value: str | None, legacy: str, effective: str) -> str | None:
    """Pure-Python twin of the SQL rule: the new value, or ``None`` when
    ``value`` is neither ``legacy`` nor strictly under ``legacy + '/'``."""
    if value is None:
        return None
    if value == legacy or value.startswith(legacy + "/"):
        return effective + value[len(legacy):]
    return None


def _bundled(env: Mapping[str, str]) -> bool:
    return env.get("SETVAULT_PG_EMBEDDED") == "1"


def _effective(env: Mapping[str, str], legacy: str, var: str) -> str | None:
    eff = env.get(var)
    if not eff:
        return None
    if len(eff) > 1:
        eff = eff.rstrip("/")
    if eff == legacy:
        return None
    return eff


async def repair(session: AsyncSession, env: Mapping[str, str]) -> dict[str, int]:
    """Rewrite legacy-prefixed paths; returns per-table changed counts (empty
    when not bundled). The caller commits."""
    if not _bundled(env):
        return {}
    counts: dict[str, int] = {}
    for legacy, var in LEGACY_PAIRS:
        eff = _effective(env, legacy, var)
        if eff is None:
            continue
        for table, col in _TARGETS[legacy]:
            # Table/column names come from the constant map above, never input.
            res = await session.execute(
                text(
                    f"UPDATE {table} SET {col} = :eff || substr({col}, :n) "  # noqa: S608
                    f"WHERE {col} = :legacy OR left({col}, :n1) = :legacy_slash"
                ),
                {
                    "eff": eff, "n": len(legacy) + 1, "n1": len(legacy) + 1,
                    "legacy": legacy, "legacy_slash": legacy + "/",
                },
            )
            counts[table] = counts.get(table, 0) + (res.rowcount or 0)
    return counts


def _exists(root: str, rel: str) -> bool:
    return os.path.exists(os.path.join(root, rel))


async def damage_report(
    session: AsyncSession, env: Mapping[str, str],
) -> tuple[int, list[str]]:
    """Count sets under the repaired media root whose audio file is missing on
    disk. Returns (missing count, first 20 slugs)."""
    if not _bundled(env):
        return 0, []
    eff = _effective(env, "/srv/media", "SETVAULT_MEDIA_PATH")
    if eff is None:
        return 0, []
    roots = {
        r.id: r.host_path
        for r in (
            await session.execute(select(MediaRoot).where(MediaRoot.host_path == eff))
        ).scalars()
    }
    if not roots:
        return 0, []
    missing = 0
    slugs: list[str] = []
    last_id = None
    while True:
        q = (
            select(LiveSet.id, LiveSet.slug, LiveSet.audio_path, LiveSet.media_root_id)
            .where(LiveSet.media_root_id.in_(roots))
            .order_by(LiveSet.id)
            .limit(_BATCH)
        )
        if last_id is not None:
            q = q.where(LiveSet.id > last_id)
        rows = (await session.execute(q)).all()
        if not rows:
            break
        for set_id, slug, audio_path, root_id in rows:
            last_id = set_id
            if not _exists(roots[root_id], audio_path):
                missing += 1
                if len(slugs) < 20:
                    slugs.append(slug)
    return missing, slugs


async def _run(env: Mapping[str, str]) -> None:
    async with session_factory()() as s:
        try:
            counts = await repair(s, env)
            if any(counts.values()):
                await audit_log(
                    s, actor_user_id=None, actor_kind="system",
                    action="storage.legacy_paths_repaired",
                    target_type="system", after=counts,
                )
            await s.commit()
        except BaseException:
            await s.rollback()
            raise
        if any(counts.values()):
            print(f"[setvault] repaired legacy paths: {counts}")
        missing, slugs = await damage_report(s, env)
        if missing:
            print(
                f"[setvault] WARNING: {missing} set file(s) missing under the media "
                f"root (first: {', '.join(slugs)}). Mount your library at /data/media.",
                file=sys.stderr,
            )


def main() -> None:
    """CLI entrypoint run from init-db.sh after migrations. Never fails boot."""
    try:
        if DATABASE_URL_ENV in os.environ:
            init_engine(os.environ[DATABASE_URL_ENV])
        run_job(_run(os.environ))
    except Exception as exc:
        print(f"[setvault] legacy path repair failed: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
