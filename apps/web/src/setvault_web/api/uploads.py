"""tusd hook receiver.

Translates tusd lifecycle events (``pre-create``, ``post-finish``) into
LiveSet drafts and pipeline jobs. The endpoint is the only ingest path that
runs without a CSRF token (tusd cannot send one) — see ``middleware/csrf.py``
``EXEMPT_PATHS``.

Authentication is replayed from the original browser session cookie that tusd
forwards in ``HTTPRequest.Header.Cookie``; we verify it with the same
``SessionSigner`` used by ``deps.current_user`` so an attacker cannot post
hooks directly without a valid logged-in session.
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from setvault_core.jobs.pipeline import PIPELINE_JOB_TIMEOUT
from setvault_core.models.catalog import LiveSet, MediaRoot
from setvault_core.services.sessions import SESSION_COOKIE, SessionSigner
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from setvault_web import tusd_hooks
from setvault_web.config import get_settings
from setvault_web.deps import db_session

router = APIRouter(prefix="/api/uploads", tags=["uploads"])


def _user_id_from_hook_cookies(headers: dict[str, list[str]]) -> str | None:
    """Extract + verify the ``session`` cookie from the forwarded HTTP headers.

    tusd forwards request headers as a ``{name: [values]}`` map. The ``Cookie``
    header may contain multiple ``k=v`` pairs separated by ``;``.
    """
    cookies_raw = headers.get("Cookie") or []
    if not cookies_raw:
        return None
    signer = SessionSigner(get_settings().secret_key)
    for entry in cookies_raw:
        for chunk in entry.split(";"):
            k, _, v = chunk.strip().partition("=")
            if k == SESSION_COOKIE:
                data = signer.read(v)
                if data is not None:
                    return data.user_id
    return None


@router.post("/tusd-hooks")
async def tusd_hook(
    request: Request,
    session: Annotated[AsyncSession, Depends(db_session)],
) -> dict[str, Any]:
    body = await request.json()
    event_type = body.get("Type")
    event = body.get("Event", {}) or {}
    headers = (event.get("HTTPRequest") or {}).get("Header") or {}

    user_id = _user_id_from_hook_cookies(headers)
    if not user_id:
        raise HTTPException(
            status_code=401, detail="upload requires an authenticated session",
        )

    if event_type == "pre-create":
        meta = (event.get("Upload") or {}).get("MetaData") or {}
        if not meta.get("filename"):
            raise HTTPException(status_code=400, detail="filename metadata required")
        # Return an empty ChangeFileInfo so tusd accepts the upload unchanged.
        return {"ChangeFileInfo": {}}

    if event_type == "post-finish":
        upload = event.get("Upload") or {}
        meta = upload.get("MetaData") or {}
        path = Path((upload.get("Storage") or {}).get("Path") or "")
        # Local-FS stat on the upload spool — fast, no need to off-thread.
        if not path.exists():  # noqa: ASYNC240
            raise HTTPException(status_code=400, detail="upload storage missing")
        filename = tusd_hooks.normalize_filename(meta.get("filename", "upload"))
        mime = tusd_hooks.sniff_mime(path)
        if mime not in tusd_hooks.ALLOWED_MIMES:
            raise HTTPException(
                status_code=415, detail=f"unsupported audio MIME: {mime}",
            )

        root = (
            await session.execute(
                select(MediaRoot)
                .where(
                    MediaRoot.default_for_ingest.is_(True),
                    MediaRoot.enabled.is_(True),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if root is None:
            raise HTTPException(
                status_code=409, detail="no default MediaRoot configured",
            )

        set_id = uuid.uuid4()
        dest = Path(root.host_path) / "originals" / str(set_id) / filename
        tusd_hooks.hardlink_or_copy(path, dest)

        relative = f"originals/{set_id}/{filename}"
        live = LiveSet(
            id=set_id,
            slug=f"upload-{set_id.hex[:8]}",
            title=meta.get("filename", filename),
            media_root_id=root.id,
            audio_path=relative,
            status="processing",
            source_type="upload",
            uploaded_by=uuid.UUID(user_id),
        )
        session.add(live)
        await session.commit()

        tusd_hooks.queue().enqueue(
            "setvault_core.jobs.pipeline.run_pipeline",
            live_set_id=str(set_id),
            job_timeout=PIPELINE_JOB_TIMEOUT,
        )
        return {"live_set_id": str(set_id)}

    # Other event types (pre-finish, post-create, etc.) are accepted but no-op.
    return {}
