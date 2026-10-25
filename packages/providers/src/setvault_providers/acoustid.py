from __future__ import annotations

import asyncio
import json
import os
import subprocess  # list-form invocations only, never shell=True
import tempfile
from pathlib import Path
from typing import ClassVar

import httpx

from setvault_providers.base import (
    Capability,
    ProviderError,
    ProviderRateLimited,
    TrackCandidate,
)


class AcoustIdProvider:
    kind = "acoustid"
    capabilities: ClassVar[set[Capability]] = {Capability.FINGERPRINT}

    def __init__(self, api_key: str, base_url: str = "https://api.acoustid.org/v2"):
        if not api_key:
            raise ValueError("AcoustID requires an application API key")
        self.api_key = api_key
        self.base_url = base_url

    def _extract_window(
        self, audio_path: str, start_seconds: int, window_seconds: int
    ) -> Path:
        """Use ffmpeg to extract a window centered on start_seconds. Returns temp file path.

        Uses list-form subprocess invocation (no shell), so audio_path is passed as an
        argv element rather than substituted into a shell command.
        """
        fd, name = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        tmp = Path(name)
        ss = max(0, start_seconds - window_seconds // 2)
        argv = ["ffmpeg", "-y", "-ss", str(ss), "-t", str(window_seconds),
                "-i", audio_path, "-ar", "44100", "-ac", "1", str(tmp)]
        res = subprocess.run(argv, capture_output=True, check=False)  # noqa: S603
        if res.returncode != 0:
            raise ProviderError(f"ffmpeg failed: {res.stderr.decode()[:200]}")
        return tmp

    async def _run_fpcalc(self, path: Path, length: int) -> dict:
        """Run chromaprint's fpcalc binary, return {duration, fingerprint}."""
        proc = await asyncio.create_subprocess_exec(
            "fpcalc", "-json", "-length", str(length), str(path),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        out, err = await proc.communicate()
        if proc.returncode != 0:
            raise ProviderError(f"fpcalc failed: {err.decode()[:200]}")
        return json.loads(out.decode())

    async def fingerprint(
        self, audio_path: str, start_seconds: int, window_seconds: int
    ) -> list[TrackCandidate]:
        window = self._extract_window(audio_path, start_seconds, window_seconds)
        try:
            fp = await self._run_fpcalc(window, window_seconds)
            async with httpx.AsyncClient(timeout=20.0) as c:
                r = await c.post(f"{self.base_url}/lookup", data={
                    "client": self.api_key,
                    "duration": str(fp["duration"]),
                    "fingerprint": fp["fingerprint"],
                    "meta": "recordings",
                })
            if r.status_code == 429:
                raise ProviderRateLimited("acoustid 429")
            if r.status_code != 200:
                raise ProviderError(f"acoustid {r.status_code}")
            data = r.json()
        finally:
            try:
                window.unlink()
            except OSError:
                pass
        if data.get("status") != "ok":
            return []
        cands: list[TrackCandidate] = []
        for hit in data.get("results", []):
            for rec in hit.get("recordings", []):
                artist = (rec.get("artists") or [{}])[0].get("name", "")
                cands.append(TrackCandidate(
                    title=rec.get("title", ""),
                    artist_name=artist,
                    confidence=float(hit.get("score", 0.0)),
                    external_ids={"acoustid": hit["id"], "musicbrainz": rec.get("id", "")},
                ))
        return cands

    async def enrich_artist(self, artist):
        return None

    async def enrich_track(self, track):
        return None
