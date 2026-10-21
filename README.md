# SetVault

[![License: GPL-3.0](https://img.shields.io/badge/license-GPL--3.0-blue.svg)](LICENSE)
[![Container: ghcr.io](https://img.shields.io/badge/container-ghcr.io-1f6feb.svg)](https://github.com/Bardesss/setvault/pkgs/container/setvault)
[![PRs welcome](https://img.shields.io/badge/PRs-welcome-ff69b4.svg)](https://github.com/Bardesss/setvault/issues)

**Self-hosted vault for DJ live sets.** Upload FLAC/WAV/MP3 or rip from
YouTube / SoundCloud / Mixcloud / Internet Archive / Bandcamp, and get waveforms,
loudness-normalized audio, time-coded tracklists, enriched metadata, comments,
per-user RSS feeds, an embeddable player, and an installable PWA.

> Think **Mixcloud × 1001tracklists × Plex** — but for DJ live sets.

---

## ✨ Features

| Area | What you get |
|---|---|
| **Ingest** | Resumable multi-GB uploads (tus) · paste-URL rip · watch-folder auto-ingest · ffmpeg → Opus + R128 normalize · waveform peaks · chromaprint dedup |
| **Catalog** | LiveSets · Artists · Venues · Series · Parties · Tags · naming templates · Postgres FTS · recycle bin · bulk editor |
| **Tracklists** | Per-set editor · reorder + time-shift · live add · paste-parse · 1001tracklists scrape · OCR |
| **Enrichment** | Pluggable providers — MusicBrainz · Discogs · AcoustID — with per-row + bulk resolve |
| **Player** | wavesurfer.js · 0.5×–2× pitch-preserved speed · A↔B loop · mediaSession · persisted per-user state |
| **Engagement** | Comments w/ @mentions + waveform markers · bookmarks · private notes · in-app + email notifications |
| **Distribution** | Per-user RSS feeds · HMAC-signed short-TTL enclosures · public `/embed/[slug]` player |
| **PWA** | Installable · offline set-detail · audio cache with admin cap + eviction · phone-width everywhere |
| **Admin** | Library webhooks · scheduled tasks · storage health · streaming backup · audit log |
| **Ops** | Multi-arch GHCR images · SBOM + cosign signatures · Alembic migrations · hardened containers |

Full feature list and release notes: [CHANGELOG.md](CHANGELOG.md).

---

## 🚀 Deploy

One image, two ways to run it. **Prereqs:** Docker 24+, Compose v2, ~2 GB RAM, and disk for your library.

### Quick start (single container) — recommended

The all-in-one image bundles Postgres, Redis, tusd, and a Caddy proxy. Five steps from zero to running:

1. **Install Docker.** [Docker Engine](https://docs.docker.com/engine/install/) 24+ with the Compose v2 plugin (Docker Desktop includes both).

2. **Start SetVault:**
   ```bash
   docker run -d --name setvault -p 1970:1970 \
     -v setvault-data:/data \
     ghcr.io/bardesss/setvault:latest
   ```
   No secrets to set — on first boot it generates its own, runs database migrations, creates the media library uploads and rips are stored in, and starts every service under s6-overlay.

3. **Open the app** at **http://localhost:1970** (or `http://<server-ip>:1970`). Allow ~10–20 s on the very first boot while the database initializes.

4. **Create your admin account.** A first-run wizard appears on a fresh install — fill it in and you're logged in.

5. **Back up the `/data` volume.** That single volume holds the database, Redis, and all your media — snapshot it regularly.

That's it — you're ready to upload a set or paste a URL to rip.

**Going past localhost?** Add `-e BASE_URL=https://sets.example.com` and front a TLS proxy so the session cookie is `Secure` — see the **TLS & `BASE_URL`** section below.

**Scripted/headless admin** (instead of the wizard): the bundled CLI reads credentials from the environment so the password never hits the command line —
```bash
docker exec -e ADMIN_EMAIL='you@example.com' -e ADMIN_PASSWORD='min-12-chars' \
  setvault python -m setvault_web.create_admin
```
It's idempotent (promotes an existing user to admin; re-running is safe).

### Quick start with Docker Compose

Prefer a declarative file you can version and re-apply? Same bundled image, via Compose:

1. **Install Docker** with the Compose v2 plugin (see step 1 above).

2. **Create `compose.yaml`** in an empty directory:
   ```yaml
   services:
     setvault:
       image: ghcr.io/bardesss/setvault:latest
       ports:
         - "1970:1970"
       volumes:
         - setvault-data:/data
         # Live sets are stored in the media library, created automatically on
         # first boot inside the volume. To keep them on a separate disk instead,
         # bind-mount it here:
         # - /path/on/host:/data/media
       restart: unless-stopped
       # Internet-facing? Uncomment and front a TLS proxy:
       # environment:
       #   BASE_URL: "https://sets.example.com"
   volumes:
     setvault-data:
   ```

3. **Start it:** `docker compose up -d` (run from that directory).

4. **Open** http://localhost:1970 and complete the first-run wizard.

5. **Update later:** `docker compose pull && docker compose up -d` — migrations run automatically on start.

Back up the `setvault-data` volume the same as above. (The repo also ships ready-made compose files under `infra/docker/` if you'd rather clone it.)

### External datastores (compose)

For managed/shared Postgres + Redis or independent scaling — set `DATABASE_URL` and/or
`REDIS_URL` and the matching bundled datastore stays off:

```bash
cp .env.example .env   # set BASE_URL + DATABASE_URL / REDIS_URL
docker compose -f infra/docker/compose.yml up -d
```

### TLS & the `BASE_URL` rule

The session cookie's `Secure` flag is derived from your `BASE_URL` scheme, so set it to match how you serve the app:

- **Public internet** — terminate TLS at a reverse proxy and set `BASE_URL=https://your-host`. The only safe mode for a public origin.
- **VPN / LAN-only** — set `BASE_URL=http://10.x.x.x:1970`; the `http://` scheme drops `Secure` so login persists. Never expose port `1970` to the internet on an `http://` URL.
- **Tailscale serve** — point `BASE_URL` at the `https://…ts.net` name; the cookie is `Secure` automatically.

> ⚠️ **External mode:** keep `1970` behind a reverse proxy that strips client-supplied
> `X-Forwarded-For`. Direct exposure lets clients spoof those headers and defeat
> rate-limiting and the `Secure`-cookie logic. Scope trusted upstreams with `SETVAULT_FORWARDED_ALLOW_IPS`.

> **Don't rewrite the HTML:** the strict CSP pins the app's inline script by hash, so a
> proxy/CDN that minifies HTML or injects scripts (e.g. Cloudflare Auto Minify or Rocket Loader)
> breaks hydration — a blank page. Forward the HTML untouched; TLS termination alone is fine.

> **Bundled-mode caveat:** the embedded Postgres is pinned to **PG 18** and its data dir is tied to
> that major version. Use external mode (or dump/restore) for rolling major upgrades. Bundled mode is homelab-grade.

### Images & signatures

`ghcr.io/bardesss/setvault:latest` — `linux/amd64` + `linux/arm64`. **Pin an explicit tag in production.**
Every release is signed with cosign (keyless) and ships a CycloneDX SBOM on the GitHub Release:

```bash
cosign verify ghcr.io/bardesss/setvault:latest \
  --certificate-identity-regexp "https://github.com/Bardesss/setvault/.github/workflows/docker.yml@.*" \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
```

---

## ⚙️ Configuration

Config is via environment variables (`.env`). **Bundled mode needs zero required vars** —
secrets are generated on first boot and `BASE_URL` defaults to `http://localhost:1970`.
External mode needs `BASE_URL` plus `DATABASE_URL`/`REDIS_URL`. The essentials:

| Variable | Required | Notes |
|---|---|---|
| `BASE_URL` | external only | Public URL (emails, RSS, embeds). Use your `https://` URL when internet-facing. |
| `SECRET_KEY` | auto | Signs cookies + HMAC URLs. Generated if unset; rotating invalidates all sessions. |
| `POSTGRES_PASSWORD` | auto (bundled) | Generated if unset; also feeds the synthesized `DATABASE_URL`. |
| `DATABASE_URL` / `REDIS_URL` | optional | Set to use external datastores; unset = bundled. |
| `SETVAULT_VERSION` | optional | Image tag — **pin in production** (default floats on `latest`). |
| `PUID` / `PGID` | optional | Container user/group for bind-mount permissions (default `1000`). |

`SETVAULT_DEV_SEED` enables a public test-only seed endpoint — **never set it in production**.
See [CHANGELOG.md](CHANGELOG.md) / `.env.example` for the full list (paths, ports, advanced proxy flags).

---

## 🔄 Upgrading

```bash
docker compose pull && docker compose up -d   # migrations run automatically on start
```

Read the [CHANGELOG](CHANGELOG.md) before any major/minor bump. Notably, bundled mode moved to
**Postgres 18** in `v0.6.0`: a PG 16 data dir is not compatible — back up on 16, start `v0.6.0`+ on a
fresh data dir, and restore (see below).

> ⚠️ **Upgrading a bundled install from ≤ 0.19.x**
>
> Older bundled images kept media, config and watch folders under `/srv` inside the container
> unless you mounted them, so they lived in the container layer and **an update threw them away**.
> New images keep everything under `/data`. Check whether you're affected:
>
> ```bash
> docker exec <container> sh -c 'printenv | grep SETVAULT_; du -sh /srv/media /srv/config'
> ```
>
> You're affected if `SETVAULT_MEDIA_PATH=/srv/media`, those paths aren't mounts, and `du` shows data.
> Then run this **before** pulling the new image (`-n` never overwrites; copying the cache is optional):
>
> ```bash
> docker exec <container> sh -c 'cp -an /srv/media/. /data/media/ && cp -an /srv/config/. /data/config/ && cp -an /srv/watch/. /data/watch/'
> ```
>
> - **Hard links:** media hardlinked from watch folders become separate copies (more disk use).
> - **If you skip it**, files already in the container layer are lost on update. The boot log
>   warns and lists the sets whose audio is gone. Database paths pointing at `/srv` are repointed
>   at `/data` automatically on boot.
> - **SECRET_KEY:** if you never set it and `.secrets` sat in the layer, each past update made a new
>   key. Users must sign in again, and SMTP or connector settings saved under an old key must be re-entered.
> - **Sessions:** signed-in sessions survive this upgrade. From now on, disabling a user or
>   changing/resetting a password signs that user out everywhere.
> - **External mode:** a `.secrets` file on a host bind mount is now `root`-owned `0600`; read it with `sudo`.
> - **Postgres names:** mixed-case `POSTGRES_DB` / `POSTGRES_USER` are now kept as given. Changing
>   `POSTGRES_USER` after first boot isn't supported: the database stays owned by the original role.

## 💾 Backup & restore

The admin backup endpoint streams a tarball of a fresh `pg_dump` + your media:

```bash
curl -fsSL -o setvault-backup-$(date +%F).tar \
  -b 'session=...' -H 'X-CSRF-Token: ...' https://your-instance/api/admin/backup
```

Restore is the inverse via the bundled CLI. It is **destructive** and refuses to run without `--yes`:

```bash
docker cp setvault-backup.tar setvault:/data/restore.tar
docker exec setvault python -m setvault_web.restore /data/restore.tar --yes
```

---

## 🌐 Translations

Translation-ready via [Crowdin](https://crowdin.com/project/setvault) — contributions welcome.
English source pushes up automatically and Crowdin opens PRs back with translated locales.
Keep `{placeholders}` intact and badges/hints short.

---

## 🛠 Local development

```bash
# Backend (FastAPI + uvicorn):
uv sync --all-extras --all-groups
uv run alembic upgrade head
uv run uvicorn setvault_web.main:app --reload --port 1970

# Frontend (SvelteKit, hot reload):
cd frontend && npm install && npm run dev -- --port 4173
```

`infra/docker/compose.dev.yml` runs Postgres + Redis + tusd locally for the backend to talk to.

### Build & run the image from source

To test the full bundled image from your checkout instead of pulling `ghcr.io/bardesss/setvault`:

```bash
# Build the all-in-one image (SvelteKit + Python + s6, multi-stage)
docker build -f infra/docker/Dockerfile -t setvault:local .

# Run it exactly like the published image
docker run --rm -p 1970:1970 -v setvault-data:/data \
  -e BASE_URL=http://localhost:1970 setvault:local
```

Then open `http://localhost:1970`. To test under Compose, point the service's `image:` at `setvault:local`. Rebuild after changing any source (frontend, backend, or `infra/docker/`).

---

## 🏛 Architecture

```
browsers ─▶ web :1970 ─┬─▶ tusd /uploads
                       └─▶ worker (RQ) ─▶ watcher (filesystem events)
                                │
            Postgres 18 ◀───────┼───────▶ Redis 7 · ffmpeg + fpcalc
```

- **`apps/web`** — FastAPI + bundled SvelteKit
- **`apps/worker`** — RQ worker (transcode / waveform / enrichment) + `watchdog` watcher
- **`packages/core`** — SQLAlchemy models, services, RQ job entrypoints
- **`packages/providers`** — metadata provider plugins (MusicBrainz / Discogs / AcoustID)
- **`frontend/`** — SvelteKit source (built into the web image); design language in `frontend/design/`
- **`infra/`** — Alembic migrations + Dockerfiles + compose stacks

---

## 🔒 Security

- Argon2 hashing · pure-ASGI CSRF + security-headers middleware · strict CSP/HSTS · HMAC-signed short-TTL URLs
- SSRF allowlist on URL-rip ingest · Redis rate-limiting on login + URL-rip · exact-pinned `yt-dlp`
- `no-new-privileges` + `cap_drop: ALL` on every container · audit log of every state-changing admin action

> **Defense-in-depth:** `yt-dlp` follows redirects without an internal-IP guard, so firewall
> container egress to block the cloud metadata endpoint (`169.254.169.254`) and RFC-1918 / link-local
> ranges. This stops a redirect-based SSRF even if it slips past the host allowlist.

Report security issues privately to the maintainer, not via public GitHub issues.

---

## 📋 Status

Shipped through the **7.x "ingest power tools"** line (URL rip, multi-source search, monitored entities);
casting, Subsonic API, smart playlists, and OIDC are on the roadmap. Each phase ships as a PR with
conventional commits driving the CHANGELOG — see [CHANGELOG.md](CHANGELOG.md) for the full history and what's next.

---

## 🤖 AI-assisted disclosure

SetVault is built with substantial help from AI coding assistants (primarily Claude Code). Every change is
reviewed, tested, and shipped by the human maintainer, but the bulk of the code is co-authored with an LLM
(commits carry `Co-Authored-By: Claude ...`).

## 📄 License

GPL-3.0-or-later — see [LICENSE](LICENSE). Free to use, modify, and self-host; distributed modifications stay
GPL-3.0, and SaaS resale requires making source available to your users under the same terms.

## 🙏 Credits

**wavesurfer.js** · **yt-dlp** · **tusd** · **MusicBrainz / Discogs / AcoustID** · **Crowdin** — and every CI red that got us here.
</content>
