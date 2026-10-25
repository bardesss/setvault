from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_core.models.catalog import Artist, Party, Venue
from setvault_core.models.monitors import Monitor

CATALOG_MODELS = {"artist": Artist, "party": Party, "venue": Venue}

# Fields PUT /api/monitors/{id} may change, and the ones audit rows describe.
EDITABLE = ("enabled", "query_text", "source_kind", "per_poll_cap")
AUDITED = ("kind", *EDITABLE, "external_id", "catalog_kind", "catalog_id")


class CatalogLinkError(ValueError):
    """The catalog entity a monitor would link to is unknown or merged."""


def _validate(kind: str, query_text: str | None, source_kind: str | None,
              external_id: str | None) -> None:
    if kind == "query":
        if not (query_text and query_text.strip()):
            raise ValueError("query monitor requires query_text")
    elif kind == "entity":
        if not source_kind or not external_id:
            raise ValueError("entity monitor requires source_kind and external_id")
    else:
        raise ValueError(f"unknown monitor kind {kind!r}")


def audit_fields(m: Monitor) -> dict:
    return {f: getattr(m, f) for f in AUDITED}


async def create_monitor(
    session: AsyncSession, *, owner_user_id: uuid.UUID, kind: str,
    query_text: str | None, source_kind: str | None, external_id: str | None,
    per_poll_cap: int = 5,
    catalog_kind: str | None = None, catalog_id: uuid.UUID | None = None,
) -> Monitor:
    _validate(kind, query_text, source_kind, external_id)
    if catalog_kind is not None:
        await check_catalog_link(session, kind, catalog_kind, catalog_id)
    m = Monitor(
        owner_user_id=owner_user_id, kind=kind,
        query_text=query_text.strip() if query_text else None,
        source_kind=source_kind, external_id=external_id,
        enabled=True, per_poll_cap=per_poll_cap,
        catalog_kind=catalog_kind, catalog_id=catalog_id,
    )
    session.add(m)
    await session.flush()
    return m


async def check_catalog_link(
    session: AsyncSession, kind: str, catalog_kind: str, catalog_id: uuid.UUID | None,
) -> None:
    """Raise CatalogLinkError unless ``kind`` is query and the entity exists
    and is not a merged tombstone."""
    if kind != "query":
        raise CatalogLinkError("only query monitors can link to a catalog entity")
    model = CATALOG_MODELS.get(catalog_kind)
    if model is None or catalog_id is None:
        raise CatalogLinkError("catalog_kind and catalog_id go together")
    entity = await session.get(model, catalog_id)
    if entity is None or entity.merged_into_id is not None:
        raise CatalogLinkError(f"unknown {catalog_kind}")


async def lock_catalog_link(
    session: AsyncSession, owner_user_id: uuid.UUID, catalog_kind: str, catalog_id: uuid.UUID,
) -> None:
    """Serialise create-or-reenable for one (owner, entity) until commit, so a
    double-clicked "Monitor" button can't create two linked monitors."""
    key = f"monitor:{owner_user_id}:{catalog_kind}:{catalog_id}"
    await session.execute(select(func.pg_advisory_xact_lock(func.hashtext(key))))


async def find_catalog_monitor(
    session: AsyncSession, *, owner_user_id: uuid.UUID, catalog_kind: str,
    catalog_id: uuid.UUID,
) -> Monitor | None:
    """The owner's monitor linked to this entity (the oldest, if several)."""
    return (await session.execute(
        select(Monitor).where(
            Monitor.owner_user_id == owner_user_id,
            Monitor.catalog_kind == catalog_kind,
            Monitor.catalog_id == catalog_id,
        ).order_by(Monitor.created_at, Monitor.id).limit(1)
    )).scalar_one_or_none()


async def catalog_refs(
    session: AsyncSession, monitors: list[Monitor],
) -> dict[tuple[str, uuid.UUID], tuple[str, str]]:
    """(catalog_kind, catalog_id) -> (name, slug) for the live entities the
    monitors link to: one query per kind. Gone or merged entities are absent."""
    wanted: dict[str, set[uuid.UUID]] = {}
    for m in monitors:
        if m.catalog_kind in CATALOG_MODELS and m.catalog_id is not None:
            wanted.setdefault(m.catalog_kind, set()).add(m.catalog_id)
    out: dict[tuple[str, uuid.UUID], tuple[str, str]] = {}
    for kind, ids in wanted.items():
        model = CATALOG_MODELS[kind]
        rows = await session.execute(
            select(model.id, model.name, model.slug)
            .where(model.id.in_(ids), model.merged_into_id.is_(None))
        )
        for eid, name, slug in rows:
            out[(kind, eid)] = (name, slug)
    return out


async def list_monitors(
    session: AsyncSession, *, owner_user_id: uuid.UUID | None = None,
) -> list[Monitor]:
    """List monitors. Pass ``owner_user_id`` to scope to one owner (non-admin
    callers); ``None`` returns all monitors (admin/curator view)."""
    q = select(Monitor).order_by(Monitor.created_at.desc())
    if owner_user_id is not None:
        q = q.where(Monitor.owner_user_id == owner_user_id)
    return list((await session.execute(q)).scalars())


def _owned(m: Monitor | None, owner_user_id: uuid.UUID | None) -> bool:
    """True if the monitor exists and the caller may act on it. ``None`` owner
    means an unrestricted (admin) caller."""
    return m is not None and (owner_user_id is None or m.owner_user_id == owner_user_id)


async def update_monitor(
    session: AsyncSession, monitor_id: uuid.UUID, changes: dict,
    *, owner_user_id: uuid.UUID | None = None,
) -> tuple[Monitor, dict, dict] | None:
    """Apply ``changes`` (a subset of EDITABLE). Returns the monitor and the
    before/after of the fields that actually changed, or ``None`` when the
    monitor is missing or not the caller's. Raises ValueError when the result
    would be an invalid monitor (e.g. a query monitor without a query)."""
    m = await session.get(Monitor, monitor_id)
    if not _owned(m, owner_user_id):
        return None
    changes = {k: v for k, v in changes.items() if k in EDITABLE}
    if isinstance(changes.get("query_text"), str):
        changes["query_text"] = changes["query_text"].strip() or None
    merged = {f: getattr(m, f) for f in EDITABLE} | changes
    _validate(m.kind, merged["query_text"], merged["source_kind"], m.external_id)
    before, after = {}, {}
    for field, value in changes.items():
        if getattr(m, field) != value:
            before[field], after[field] = getattr(m, field), value
            setattr(m, field, value)
    await session.flush()
    return m, before, after


async def delete_monitor(
    session: AsyncSession, monitor_id: uuid.UUID,
    *, owner_user_id: uuid.UUID | None = None,
) -> dict | None:
    """Delete the monitor; returns its audit fields, or ``None`` when it is
    missing or not the caller's."""
    m = await session.get(Monitor, monitor_id)
    if not _owned(m, owner_user_id):
        return None
    before = audit_fields(m)
    await session.delete(m)
    await session.flush()
    return before


async def due_monitors(
    session: AsyncSession, *, interval_seconds: int, now: datetime,
) -> list[Monitor]:
    """Enabled monitors never checked or last checked older than the interval."""
    cutoff = now - timedelta(seconds=interval_seconds)
    return list((await session.execute(
        select(Monitor).where(
            Monitor.enabled.is_(True),
            or_(Monitor.last_checked_at.is_(None), Monitor.last_checked_at < cutoff),
        )
    )).scalars())
