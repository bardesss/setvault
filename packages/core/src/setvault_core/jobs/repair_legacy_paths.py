"""Boot-time repair of legacy ``/srv`` paths stored in the DB.

Old images forced ``SETVAULT_MEDIA_PATH=/srv/media`` even in bundled mode, so
existing bundled installs persist ``/srv/media`` (and watch folders under
``/srv/watch``) in their database. Bundled mode now keeps data under ``/data``;
this job repoints those rows so ingest keeps working.

Idempotent and conservative: only runs in bundled mode, only rewrites values
equal to the legacy prefix or strictly below it (``/srv/media2`` is untouched),
and does nothing when the effective path equals the legacy one. Rows at or
below a live mount point under a legacy prefix (for example a user-mounted
watch folder ``/srv/watch/incoming``) are left alone: that path is real.
"""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Iterable, Mapping

from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_core.db import init_engine, run_job, session_factory
from setvault_core.jobs.email import DATABASE_URL_ENV
from setvault_core.models.catalog import LiveSet, MediaRoot
from setvault_core.services.audit import log as audit_log

LEGACY_PAIRS: tuple[tuple[str, str], ...] = (
    ("/srv/media", "SETVAULT_MEDIA_PATH"),
    ("/srv/watch", "SETVAULT_WATCH_FOLDERS_PATH"),
)

# Every legacy prefix is applied to every one of these (table, column) targets;
# the strict prefix match keeps look-alikes safe.
_TARGETS: tuple[tuple[str, str], ...] = (
    ("media_roots", "host_path"),
    ("watch_folders", "host_path"),
    ("unmatched_files", "file_path"),
    ("live_sets", "source_url"),
)

# Targets whose column has a unique constraint. A row whose rewritten value is
# already taken is skipped instead of failing the transaction.
_UNIQUE: frozenset[tuple[str, str]] = frozenset({("watch_folders", "host_path")})

_BATCH = 500

MOUNTINFO = "/proc/self/mountinfo"
_OCTAL = re.compile(rb"\\([0-7]{3})")


def rewrite_prefix(value: str | None, legacy: str, effective: str) -> str | None:
    """Pure-Python twin of the SQL rule: the new value, or ``None`` when
    ``value`` is neither ``legacy`` nor strictly under ``legacy + '/'``."""
    if value is None:
        return None
    if value == legacy or value.startswith(legacy + "/"):
        return effective + value[len(legacy):]
    return None


def _unescape_mount(field: str) -> str:
    """Decode the ``\\040``-style octal escapes the kernel uses in mountinfo."""
    raw = field.encode("utf-8", "surrogateescape")
    raw = _OCTAL.sub(lambda m: bytes([int(m.group(1), 8)]), raw)
    return raw.decode("utf-8", "surrogateescape")


def read_mounts(path: str = MOUNTINFO) -> list[str]:
    """Mount points (field 5) listed in ``path``; empty when it can't be read
    (non-Linux, no /proc)."""
    try:
        with open(path, encoding="utf-8", errors="surrogateescape") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return []
    mounts: list[str] = []
    for line in lines:
        fields = line.split(" ")
        if len(fields) >= 5:
            mounts.append(_unescape_mount(fields[4]))
    return mounts


def _under(value: str, prefix: str) -> bool:
    """``value`` equals ``prefix`` or lies strictly below ``prefix + '/'``."""
    return value == prefix or value.startswith(prefix + "/")


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


def _legacy_mounts(env: Mapping[str, str], mounts: Iterable[str]) -> list[str]:
    """Mount points at or below any legacy prefix that is being repaired."""
    legacies = [
        legacy for legacy, var in LEGACY_PAIRS if _effective(env, legacy, var) is not None
    ]
    out: list[str] = []
    for m in mounts:
        if len(m) > 1:
            m = m.rstrip("/")
        if m not in out and any(_under(m, legacy) for legacy in legacies):
            out.append(m)
    return out


def _mount_filter(col: str, mounts: list[str]) -> tuple[str, dict[str, object]]:
    """SQL fragment (and params) excluding rows equal to or under ``mounts``."""
    sql = ""
    params: dict[str, object] = {}
    for i, m in enumerate(mounts):
        sql += f" AND NOT ({col} = :m{i} OR left({col}, :mn{i}) = :ms{i})"
        params.update({f"m{i}": m, f"mn{i}": len(m) + 1, f"ms{i}": m + "/"})
    return sql, params


async def repair(
    session: AsyncSession,
    env: Mapping[str, str],
    mounts: Iterable[str] | None = None,
) -> dict[str, int]:
    """Rewrite legacy-prefixed paths; returns per-table changed counts (empty
    when not bundled). ``mounts`` defaults to the mount points in
    /proc/self/mountinfo. The caller commits."""
    if not _bundled(env):
        return {}
    skip = _legacy_mounts(env, read_mounts() if mounts is None else mounts)
    for m in skip:
        print(f"[setvault] legacy path repair: {m} is a mount, leaving paths under it unchanged")
    counts: dict[str, int] = {}
    for legacy, var in LEGACY_PAIRS:
        eff = _effective(env, legacy, var)
        if eff is None:
            continue
        for table, col in _TARGETS:
            # Table/column names come from the constant map above, never input.
            mount_sql, mount_params = _mount_filter(col, skip)
            where = (
                f"({col} = :legacy OR left({col}, :n1) = :legacy_slash){mount_sql}"
            )
            params: dict[str, object] = {
                "eff": eff, "n": len(legacy) + 1, "n1": len(legacy) + 1,
                "legacy": legacy, "legacy_slash": legacy + "/",
                **mount_params,
            }
            if (table, col) in _UNIQUE:
                # Skip (and log) rows whose new value is already taken, so one
                # collision can't roll back the whole repair.
                taken = (
                    f"EXISTS (SELECT 1 FROM {table} o "  # noqa: S608
                    f"WHERE o.{col} = :eff || substr({table}.{col}, :n))"
                )
                clashes = (await session.execute(
                    text(f"SELECT {col} FROM {table} WHERE {where} AND {taken}"),  # noqa: S608
                    params,
                )).scalars().all()
                for value in clashes:
                    print(
                        f"[setvault] legacy path repair: not repointing {table} "
                        f"{value!r}: {rewrite_prefix(value, legacy, eff)!r} already exists",
                        file=sys.stderr,
                    )
                where += f" AND NOT {taken}"
            res = await session.execute(
                text(
                    f"UPDATE {table} SET {col} = :eff || substr({col}, :n) "  # noqa: S608
                    f"WHERE {where}"
                ),
                params,
            )
            counts[table] = counts.get(table, 0) + (res.rowcount or 0)
    return counts


def _exists(root: str, rel: str) -> bool:
    return os.path.exists(os.path.join(root, rel))


async def damage_report(
    session: AsyncSession,
    env: Mapping[str, str],
    mounts: Iterable[str] | None = None,
) -> tuple[int, list[str]]:
    """Count sets under the repaired media root whose audio file is missing on
    disk, ignoring roots at or below a live legacy mount. Returns (missing
    count, first 20 slugs)."""
    if not _bundled(env):
        return 0, []
    effs = [
        e for legacy, var in LEGACY_PAIRS
        if (e := _effective(env, legacy, var)) is not None
    ]
    if not effs:
        return 0, []
    skip = _legacy_mounts(env, read_mounts() if mounts is None else mounts)
    cond = or_(*(
        or_(MediaRoot.host_path == e, MediaRoot.host_path.startswith(e + "/", autoescape=True))
        for e in effs
    ))
    roots = {
        r.id: r.host_path
        for r in (await session.execute(select(MediaRoot).where(cond))).scalars()
        if not any(_under(r.host_path, m) for m in skip)
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


async def _run(env: Mapping[str, str], mounts: Iterable[str] | None = None) -> None:
    mounts = read_mounts() if mounts is None else list(mounts)
    async with session_factory()() as s:
        try:
            counts = await repair(s, env, mounts)
            if any(counts.values()):
                await audit_log(
                    s, actor_user_id=None, actor_kind="system",
                    action="system.paths_repaired",
                    target_type="system", after=counts,
                )
            await s.commit()
        except BaseException:
            await s.rollback()
            raise
        if any(counts.values()):
            print(f"[setvault] repaired legacy paths: {counts}")
        missing, slugs = await damage_report(s, env, mounts)
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
