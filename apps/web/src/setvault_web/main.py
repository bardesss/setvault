import asyncio
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from redis.asyncio import Redis
from setvault_core.db import init_engine, session_factory
from sqlalchemy import text
from starlette.responses import FileResponse, JSONResponse

from setvault_web import __version__
from setvault_web.api import admin as admin_api
from setvault_web.api import auth as auth_api
from setvault_web.api import backup as backup_api
from setvault_web.api import backups as backups_api
from setvault_web.api import bookmarks as bookmarks_api
from setvault_web.api import bulk_action as bulk_action_api
from setvault_web.api import catalog as catalog_api
from setvault_web.api import catalog_admin as catalog_admin_api
from setvault_web.api import comments as comments_api
from setvault_web.api import connectors as connectors_api
from setvault_web.api import dev_seed as dev_seed_api
from setvault_web.api import duplicates as duplicates_api
from setvault_web.api import embed as embed_api
from setvault_web.api import enrichment as enrichment_api
from setvault_web.api import favorites as favorites_api
from setvault_web.api import feeds as feeds_api
from setvault_web.api import images as images_api
from setvault_web.api import ingest_sources as ingest_sources_api
from setvault_web.api import invites as invites_api
from setvault_web.api import jobs as jobs_api
from setvault_web.api import me as me_api
from setvault_web.api import media_roots as media_roots_api
from setvault_web.api import monitors as monitors_api
from setvault_web.api import notes as notes_api
from setvault_web.api import notifications as notifications_api
from setvault_web.api import password_reset as password_reset_api
from setvault_web.api import providers as providers_api
from setvault_web.api import recycle as recycle_api
from setvault_web.api import scheduled_tasks as scheduled_tasks_api
from setvault_web.api import search as search_api
from setvault_web.api import sets as sets_api
from setvault_web.api import setup as setup_api
from setvault_web.api import tracklist as tracklist_api
from setvault_web.api import tracks as tracks_api
from setvault_web.api import uploads as uploads_api
from setvault_web.api import url_rip as url_rip_api
from setvault_web.api import users as users_api
from setvault_web.api import wanted as wanted_api
from setvault_web.api import watch_folders as watch_folders_api
from setvault_web.api import webhooks as webhooks_api
from setvault_web.api import ws as ws_api
from setvault_web.config import get_settings
from setvault_web.middleware.csrf import CsrfMiddleware
from setvault_web.middleware.security_headers import (
    SecurityHeadersMiddleware,
    compute_inline_script_hashes,
)

logger = logging.getLogger(__name__)

HEALTH_CHECK_TIMEOUT_SECONDS = 2


async def _check_db() -> None:
    async with session_factory()() as session:
        await session.execute(text("SELECT 1"))


async def _ping_redis() -> None:
    client = Redis.from_url(
        get_settings().redis_url,
        socket_connect_timeout=1,
        socket_timeout=1,
    )
    try:
        await client.ping()
    finally:
        await client.aclose()


async def _run_check(name: str, check: Callable[[], Awaitable[None]]) -> bool:
    try:
        await asyncio.wait_for(check(), HEALTH_CHECK_TIMEOUT_SECONDS)
    except Exception:
        logger.warning("health check failed: %s", name, exc_info=True)
        return False
    return True


def create_app() -> FastAPI:
    settings = get_settings()
    init_engine(settings.database_url)
    app = FastAPI(title="SetVault", version=__version__)

    # SvelteKit's adapter-static index.html bootstraps via an inline <script>;
    # hash it so the strict `script-src 'self'` CSP admits exactly that script
    # (no 'unsafe-inline'). The placeholder shell shipped in source has none.
    static_root = Path(__file__).parent / "static"
    index_html = static_root / "index.html"
    script_hashes = (
        compute_inline_script_hashes(index_html.read_bytes())
        if index_html.is_file()
        else []
    )

    app.add_middleware(SecurityHeadersMiddleware, script_hashes=script_hashes)
    app.add_middleware(CsrfMiddleware)

    @app.get("/api/health")
    async def health() -> JSONResponse:
        db_ok, redis_ok = await asyncio.gather(
            _run_check("db", lambda: _check_db()),
            _run_check("redis", lambda: _ping_redis()),
        )
        failed = [n for n, ok in (("db", db_ok), ("redis", redis_ok)) if not ok]
        if failed:
            return JSONResponse({"status": "degraded", "failed": failed}, status_code=503)
        return JSONResponse({"status": "ok"})

    app.include_router(auth_api.router)
    app.include_router(setup_api.router)
    app.include_router(invites_api.router)
    app.include_router(password_reset_api.router)
    app.include_router(connectors_api.router)
    app.include_router(media_roots_api.router)
    app.include_router(uploads_api.router)
    app.include_router(catalog_api.router)
    app.include_router(catalog_admin_api.router)
    app.include_router(sets_api.router)
    app.include_router(tracklist_api.router)
    app.include_router(tracks_api.router)
    app.include_router(enrichment_api.router)
    app.include_router(search_api.router)
    app.include_router(ws_api.router)
    app.include_router(admin_api.router)
    app.include_router(providers_api.router)
    app.include_router(jobs_api.router)
    app.include_router(users_api.router)
    app.include_router(me_api.router)
    app.include_router(comments_api.router)
    app.include_router(bookmarks_api.router)
    app.include_router(favorites_api.router)
    app.include_router(notes_api.router)
    app.include_router(notifications_api.router)
    app.include_router(url_rip_api.router)
    app.include_router(feeds_api.router)
    app.include_router(ingest_sources_api.router)
    app.include_router(images_api.router)
    app.include_router(embed_api.router)
    app.include_router(watch_folders_api.router)
    app.include_router(recycle_api.router)
    app.include_router(duplicates_api.router)
    app.include_router(wanted_api.router)
    app.include_router(scheduled_tasks_api.router)
    app.include_router(webhooks_api.router)
    app.include_router(backup_api.router)
    app.include_router(backups_api.router)
    app.include_router(bulk_action_api.router)
    app.include_router(monitors_api.router)
    if dev_seed_api.is_enabled():
        app.include_router(dev_seed_api.router)

    # Static frontend bundle (SvelteKit adapter-static output). The build/
    # contents are dropped here by the Docker frontend stage; only a
    # placeholder index.html ships in source control. ``static_root`` was
    # resolved above for the CSP inline-script hashing.
    if static_root.exists():
        if (static_root / "_app").exists():
            app.mount(
                "/_app",
                StaticFiles(directory=static_root / "_app"),
                name="sveltekit_assets",
            )
        if (static_root / "fonts").exists():
            app.mount(
                "/fonts",
                StaticFiles(directory=static_root / "fonts"),
                name="fonts",
            )

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa_fallback(full_path: str) -> FileResponse:
            if full_path.startswith(("api/", "uploads/", "ws/")):
                raise HTTPException(status_code=404)
            candidate = static_root / full_path
            if candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(static_root / "index.html")

    return app


app = create_app()
