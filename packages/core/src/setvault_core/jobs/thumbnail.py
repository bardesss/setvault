"""Store a set's cover thumbnail next to its audio.

A rip's probe records the platform's thumbnail URL (``RipJob.probed_metadata``).
This downloads it once and keeps a local, re-encoded JPEG under
``thumbs/<set id>.jpg`` on the set's media root, so covers survive the source
upload disappearing and are served from our own origin (the CSP pins
``img-src 'self'``). Best effort: a missing or broken thumbnail never fails
the rip.
"""
from __future__ import annotations

import asyncio
import io
import logging
import os
import uuid
from pathlib import Path

from PIL import Image

from setvault_core.db import init_engine, session_factory
from setvault_core.models.catalog import LiveSet, MediaRoot
from setvault_core.services.remote_image import RemoteImageError, fetch_image

logger = logging.getLogger(__name__)

# Covers render at card size at most; 960px keeps them sharp on hi-dpi.
THUMB_MAX_PX = 960
THUMB_JPEG_QUALITY = 85
# Anything bigger than this is not a thumbnail (and could be a decompression bomb).
_MAX_SOURCE_PIXELS = 40_000_000


def _encode_jpeg(body: bytes, dest: Path) -> None:
    """Decode ``body``, shrink it to fit THUMB_MAX_PX and write a JPEG to
    ``dest`` atomically. Re-encoding means we only ever serve bytes Pillow
    produced, never whatever the upstream sent."""
    with Image.open(io.BytesIO(body)) as img:
        if img.width * img.height > _MAX_SOURCE_PIXELS:
            raise ValueError(f"thumbnail too large: {img.width}x{img.height}")
        img.draft("RGB", (THUMB_MAX_PX, THUMB_MAX_PX))
        rgb = img.convert("RGB")
    rgb.thumbnail((THUMB_MAX_PX, THUMB_MAX_PX))
    tmp = dest.with_suffix(".jpg.tmp")
    dest.parent.mkdir(parents=True, exist_ok=True)
    rgb.save(tmp, "JPEG", quality=THUMB_JPEG_QUALITY, optimize=True)
    tmp.replace(dest)


async def store_thumbnail(live_set_id: str, url: str | None) -> bool:
    """Download ``url`` as the set's thumbnail; returns whether one was stored.

    Never raises for a bad URL or image (it logs and returns False); the
    caller's pipeline carries on without a cover."""
    if not url:
        return False
    if "DATABASE_URL" in os.environ:
        init_engine(os.environ["DATABASE_URL"])
    try:
        body, _ctype = await fetch_image(url)
    except RemoteImageError as exc:
        logger.info("thumbnail for set %s not fetched: %s", live_set_id, exc)
        return False

    async with session_factory()() as s:
        live = await s.get(LiveSet, uuid.UUID(live_set_id))
        if live is None:
            return False
        root = await s.get(MediaRoot, live.media_root_id)
        if root is None:
            return False
        rel = f"thumbs/{live.id}.jpg"
        try:
            await asyncio.to_thread(_encode_jpeg, body, Path(root.host_path) / rel)
        except (OSError, ValueError, Image.DecompressionBombError) as exc:
            logger.info("thumbnail for set %s not stored: %s", live_set_id, exc)
            return False
        live.thumb_path = rel
        await s.commit()
    return True
