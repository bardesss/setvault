from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from setvault_core.db import session_factory
from setvault_core.services.system_config import get_config
from setvault_web import __version__


def test_version_matches_pyproject():
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    assert __version__ == data["project"]["version"]


@pytest.mark.asyncio
async def test_update_banner_not_outdated_when_equal(authed_admin_client):
    async with session_factory()() as s:
        config = await get_config(s)
        config.latest_release_version = "v" + __version__
        await s.commit()
    try:
        r = await authed_admin_client.get("/api/admin/health")
        assert r.status_code == 200, r.text
        assert r.json()["version"]["is_outdated"] is False
    finally:
        async with session_factory()() as s:
            config = await get_config(s)
            config.latest_release_version = None
            await s.commit()
