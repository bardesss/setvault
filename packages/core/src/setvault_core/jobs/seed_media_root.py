"""First-boot seeding of the default media root.

The Docker image mounts the user's storage folder at a fixed container path
(``SETVAULT_MEDIA_PATH`` — ``/srv/media`` external, ``/data/media`` bundled).
Radarr/Sonarr style: the mounted folder *is* the library, no in-app config
needed. This module turns that mount into a usable ``MediaRoot`` row so uploads
and rips land there with zero Settings clicks.

Idempotent and conservative: it only seeds when **no** media root exists, so an
admin who has configured their own root(s) is never overridden.
"""

from __future__ import annotations

import os

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_core.db import init_engine, run_job, session_factory
from setvault_core.jobs.email import DATABASE_URL_ENV
from setvault_core.models.catalog import MediaRoot

MEDIA_PATH_ENV = "SETVAULT_MEDIA_PATH"


async def ensure_default_media_root(
    session: AsyncSession, host_path: str, *, name: str = "Library",
) -> MediaRoot | None:
    """Create a default-for-ingest media root at ``host_path`` if the catalog
    has no media roots yet. Returns the new row, or ``None`` if one already
    existed (no-op). The caller commits."""
    existing = (await session.execute(select(MediaRoot.id).limit(1))).first()
    if existing is not None:
        return None
    # Guarantee the library directory exists so the new root is immediately
    # usable (health probes "ok", ingest can write) even if the mount target
    # hadn't been created yet.
    os.makedirs(host_path, exist_ok=True)
    root = MediaRoot(
        name=name, host_path=host_path, enabled=True, default_for_ingest=True,
    )
    session.add(root)
    await session.flush()
    return root


async def _run(host_path: str) -> None:
    async with session_factory()() as s:
        created = await ensure_default_media_root(s, host_path)
        await s.commit()
        if created is not None:
            print(f"[setvault] seeded default media root -> {host_path}")
        else:
            print("[setvault] media root already configured; leaving as-is")


def main() -> None:
    """CLI entrypoint run from init-db.sh after migrations. Re-initialises the
    engine from env vars (same pattern as the RQ job wrappers)."""
    if DATABASE_URL_ENV in os.environ:
        init_engine(os.environ[DATABASE_URL_ENV])
    host_path = os.environ.get(MEDIA_PATH_ENV, "/srv/media")
    run_job(_run(host_path))


if __name__ == "__main__":
    main()
