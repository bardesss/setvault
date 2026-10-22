from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from setvault_core.db import session_factory
from setvault_core.services.system_config import get_config

ROOT = Path(__file__).resolve().parents[3]


def _pyproject_version(rel: str) -> str:
    data = tomllib.loads((ROOT / rel / "pyproject.toml").read_text(encoding="utf-8"))
    return data["project"]["version"]


def test_version_matches_pyproject():
    import setvault_core
    import setvault_web
    import setvault_worker

    assert setvault_web.__version__ == _pyproject_version("apps/web")
    assert setvault_worker.__version__ == _pyproject_version("apps/worker")
    assert setvault_core.__version__ == _pyproject_version("packages/core")


@pytest.mark.asyncio
async def test_update_banner_not_outdated_when_equal(authed_admin_client):
    real = _pyproject_version("apps/web")
    async with session_factory()() as s:
        config = await get_config(s)
        config.latest_release_version = "v" + real
        await s.commit()
    try:
        r = await authed_admin_client.get("/api/admin/health")
        assert r.status_code == 200, r.text
        version = r.json()["version"]
        assert version["current"] == real
        assert version["is_outdated"] is False
    finally:
        async with session_factory()() as s:
            config = await get_config(s)
            config.latest_release_version = None
            await s.commit()
