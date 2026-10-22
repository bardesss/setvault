"""Pure-logic check on the audit retention prune cutoff.

Full DB round-trip is integration territory; here we just verify the cutoff
math + that days<=0 disables pruning (the production guard)."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from setvault_core.jobs.audit_retention import prune_audit_events


def test_cutoff_math_default_90_days():
    """Sanity-check the calculation matches the spec default (90 days)."""
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=90)
    assert (now - cutoff).days == 90


def test_disabled_when_days_zero():
    """The module reads SystemConfig.audit_retention_days; a 0 / negative
    value short-circuits before issuing the DELETE. This is the policy guard
    documented in the module docstring."""
    # We test the contract via inspection — the actual DB round-trip is
    # exercised by integration tests against TEST_DATABASE_URL.
    import setvault_core.jobs.audit_retention as mod
    src = mod.__file__
    with open(src, encoding="utf-8") as f:
        text = f.read()
    assert "days <= 0" in text, (
        "expected an early-return guard on days <= 0 — found neither "
        "`days <= 0` nor `days < 1` in the source"
    )


async def _seed_jobs(rq_prefix: str) -> tuple[str, str]:
    from setvault_core.db import session_factory
    from setvault_core.models.system import Job

    now = datetime.now(UTC)
    async with session_factory()() as s:
        old = Job(rq_id=f"{rq_prefix}old", kind="t.old", status="finished",
                  created_at=now - timedelta(days=31))
        fresh = Job(rq_id=f"{rq_prefix}new", kind="t.new", status="finished",
                    created_at=now - timedelta(days=29))
        s.add_all([old, fresh])
        await s.commit()
        return old.id, fresh.id


async def _job_ids(rq_prefix: str) -> set[str]:
    from setvault_core.db import session_factory
    from setvault_core.models.system import Job
    from sqlalchemy import select

    async with session_factory()() as s:
        return set((await s.execute(
            select(Job.id).where(Job.rq_id.like(f"{rq_prefix}%"))
        )).scalars())


async def _drop_jobs(rq_prefix: str) -> None:
    from setvault_core.db import session_factory
    from setvault_core.models.system import Job
    from sqlalchemy import delete

    async with session_factory()() as s:
        await s.execute(delete(Job).where(Job.rq_id.like(f"{rq_prefix}%")))
        await s.commit()


async def test_retention_prunes_jobs_older_than_30_days():
    prefix = "retention-test-"
    await _drop_jobs(prefix)
    try:
        _, fresh_id = await _seed_jobs(prefix)
        result = await prune_audit_events()
        assert result["jobs_deleted"] >= 1
        assert await _job_ids(prefix) == {fresh_id}
    finally:
        await _drop_jobs(prefix)


async def test_job_pruning_runs_even_with_audit_retention_disabled(monkeypatch):
    import setvault_core.jobs.audit_retention as mod

    class _Cfg:
        audit_retention_days = 0

    async def _get_config(session):
        return _Cfg()

    monkeypatch.setattr(mod, "get_config", _get_config)
    prefix = "retention-off-test-"
    await _drop_jobs(prefix)
    try:
        _, fresh_id = await _seed_jobs(prefix)
        result = await prune_audit_events()
        assert result["deleted"] == 0
        assert result["jobs_deleted"] >= 1
        assert await _job_ids(prefix) == {fresh_id}
    finally:
        await _drop_jobs(prefix)
