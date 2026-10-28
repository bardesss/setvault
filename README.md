# SetVault

[![License: GPL-3.0](https://img.shields.io/badge/license-GPL--3.0-blue.svg)](LICENSE)
[![Container: ghcr.io](https://img.shields.io/badge/container-ghcr.io-1f6feb.svg)](https://github.com/Bardesss/setvault/pkgs/container/setvault)
[![PRs welcome](https://img.shields.io/badge/PRs-welcome-ff69b4.svg)](https://github.com/Bardesss/setvault/issues)

**Self-hosted vault for DJ live sets.** Upload FLAC/WAV/MP3 or rip from
YouTube / SoundCloud / Mixcloud / Internet Archive / Bandcamp, and get waveforms,
loudness-matched streams, time-coded tracklists, enriched metadata, comments,
per-user RSS feeds, an embeddable player, and an installable PWA.

> Think **Mixcloud × 1001tracklists × Plex** — but for DJ live sets.

---

## ✨ Features

| Area | What you get |
|---|---|
| **Ingest** | Resumable multi-GB uploads (tus) · paste-URL rip · watch-folder auto-ingest · ffmpeg → Opus, EBU R128 measured, static gain to a target loudness · waveform peaks · chromaprint fingerprinting with duplicate scan + cleanup |
| **Quality** | Quality upgrades against a cutoff, worked through on the Wanted, Quality and Duplicates admin pages |
| **Catalog** | LiveSets · Artists · Venues · Series · Parties · Tags · naming templates · Postgres FTS · recycle bin · bulk editor · browse pages · Home activity + storage · entity monitors ("Monitor this") |
| **Tracklists** | Per-set editor · reorder + time-shift · live add · paste-parse · 1001tracklists scrape · OCR |
| **Enrichment** | Pluggable providers — MusicBrainz · Discogs · AcoustID — with per-row + bulk resolve |
| **Player** | wavesurfer.js · 0.5×–2× pitch-preserved speed · A↔B loop · mediaSession · persisted per-user state · listening history · playlists · play queue synced across devices |
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

**Locked out?** Reset the admin password from inside the container. With one admin, `--email` is optional (pass `--email you@example.com` if there are several). Print a one-hour reset link and open it in the browser:
```bash
docker exec -it setvault python -m setvault_web.reset_password --link
```
Or set a new password directly. It is read from `NEW_PASSWORD` or prompted for, so it never hits the command line:
```bash
docker exec -it setvault python -m setvault_web.reset_password
```
Either way, existing sessions are signed out and the reset is written to the audit log.

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
| `TZ` | optional | Time zone for the nightly backup time (default `UTC`). |
| `SETVAULT_BACKUP_PATH` | optional | External compose: host folder for nightly DB backups (default `./.data/backups`). |

`SETVAULT_DEV_SEED` enables a public test-only seed endpoint — **never set it in production**.
See [CHANGELOG.md](CHANGELOG.md) / `.env.example` for the full list (paths, ports, advanced proxy flags).

---

## 🔄 Upgrading

```bash
docker compose pull && docker compose up -d   # migrations run automatically on start
```

After upgrading to a release that adds fingerprinting or quality data, open **Admin → Quality → Run backfill** once so existing sets get fingerprinted and measured. The set size backfill runs by itself when the worker starts.

Read the [CHANGELOG](CHANGELOG.md) before any major/minor bump. Notably, bundled mode moved to
**Postgres 18** since the 0.6 release: a PG 16 data dir is not compatible — back up on 16, start 0.6 or later on a
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
> - **SECRET_KEY in env now wins:** if the boot log says "using SECRET_KEY from environment
>   (persisted value ignored)", the key in your env is used instead of the one in `.secrets` (before,
>   it was the other way round). To keep existing sessions and saved connector settings, set
>   `SECRET_KEY` to the value in `.secrets`.
> - **Sessions:** signed-in sessions survive this upgrade. From now on, disabling a user or
>   changing/resetting a password signs that user out everywhere.
> - **External mode:** a `.secrets` file on a host bind mount is now `root`-owned `0600`; read it with `sudo`.
> - **Postgres names:** mixed-case `POSTGRES_DB` / `POSTGRES_USER` are now kept as given. Changing
>   `POSTGRES_USER` after first boot isn't supported: the database stays owned by the original role.

## 💾 Backup & restore

### Scheduled database backups

SetVault backs up its database every night (on by default, 03:30). Each backup is a gzipped
`pg_dump` named `setvault-YYYYMMDD-HHMMSS.sql.gz`; the newest 14 are kept. Change the time,
retention and folder under **Admin → Backups**, which also lists, downloads and deletes the files
and has a "Back up now" button. A failed backup shows in red there and notifies the admins.

- **Where:** `/data/backups` in bundled mode (inside the `/data` volume). With the external
  compose files it's the `/srv/backups` mount, set by `SETVAULT_BACKUP_PATH` in `.env`
  (default `./.data/backups`). A folder that is neither under `/data` nor a mount is lost when
  the container is recreated; the Backups tab warns about that.
- **When:** `backup_time` is in the container's time zone. Set `TZ` (e.g. `TZ=Europe/Amsterdam`);
  the default is `UTC`. If the container was down at that time, the backup runs at the next
  hourly check the same day.
- **Space:** a backup refuses to start when the folder has less than twice the previous
  backup's size free.
- **What's not in it:** your media (it's large and already on your disk) and `.secrets` (the key
  that decrypts saved connector passwords doesn't belong next to them; after a restore on a new
  install, re-enter SMTP and connector passwords). Keep the backup folder on a **different disk**
  if you want protection against losing the disk, and back up your media separately.

### Restore from a scheduled backup

The restore CLI loads a `.sql.gz` into the database (media is untouched). It is **destructive**
and refuses to run without `--yes`:

```bash
# bundled: backups are already inside the container
docker exec setvault python -m setvault_web.restore /data/backups/setvault-20261023-033000.sql.gz --yes
# external compose: the backups mount is /srv/backups
docker compose exec setvault python -m setvault_web.restore /srv/backups/setvault-20261023-033000.sql.gz --yes
```

Restart the container afterwards so every process picks up the restored data.

### Full export (database + media)

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

## 🔔 Webhooks

Admin → Webhooks sends an HTTP POST to a URL when a set is published, updated, deleted, restored or purged. Each webhook is signed with its own secret, which is shown once when you create it or rotate it. Header values (for example a Plex token) are stored encrypted and are never shown again. Failed deliveries are retried (network errors, timeouts, 5xx, 408 and 429), and the newest 50 deliveries per webhook are listed on the page.

### Verifying webhook signatures

Every delivery carries four headers:

- `X-SetVault-Event`: the event name, for example `set.published`.
- `X-SetVault-Delivery`: a unique id per delivery, the same on every retry.
- `X-SetVault-Timestamp`: unix seconds of this attempt.
- `X-SetVault-Signature`: `sha256=<hex>`, an HMAC-SHA256 of the string `"{timestamp}.{raw body}"` keyed with the webhook secret.

Verify against the raw request body exactly as received, not a re-serialised copy:

```python
import hmac, hashlib, time

def verify(secret: str, headers, raw_body: bytes) -> bool:
    ts = headers["X-SetVault-Timestamp"]
    if abs(time.time() - int(ts)) > 300:  # reject anything older than 5 minutes
        return False
    mac = hmac.new(secret.encode(), ts.encode() + b"." + raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest("sha256=" + mac, headers["X-SetVault-Signature"])
```

Reject timestamps older than 5 minutes to stop replayed requests.

---

## ▶️ YouTube: sign-in / bot check

YouTube sometimes answers yt-dlp with *"Sign in to confirm you're not a bot"*,
mostly on homelab and datacenter IPs. URL rips and source searches then fail
with that message. SetVault handles this in two layers.

**Out of the box.** The image includes [Deno](https://deno.com), which runs
yt-dlp's YouTube challenge solver (`yt-dlp-ejs`). It also runs the
[bgutil PO-token server](https://github.com/Brainicism/bgutil-ytdlp-pot-provider)
on `127.0.0.1:4416` (s6 service `pot-provider`). yt-dlp's bgutil plugin fetches
proof-of-origin tokens from it automatically. On many IPs this is enough, and
there's nothing to set up.

**If the bot check persists, upload cookies.** In **Admin → Sources → YouTube
cookies**, upload a `cookies.txt` from a browser that is logged in to YouTube:

1. Log in to YouTube in a private window with a **throwaway Google account**.
   Anyone holding the cookies is logged in as that account.
2. Export the cookies in Netscape format with an extension such as
   *Get cookies.txt LOCALLY*, then close the window without logging out.
3. Upload the file. SetVault accepts Netscape cookie files up to 1 MB. It
   shows when the file was uploaded and how many YouTube cookies it holds,
   but never shows the cookies themselves.

The file is stored owner-only as `youtube-cookies.txt` in the config volume
(`/data/config` bundled, `/srv/config` with external compose). yt-dlp gets a
throwaway copy for each call, so it never rewrites your upload. Cookies expire
or get revoked. When the bot check comes back, the error says so; export and
upload the cookies again, or use **Remove** to stop sending them.

---

## 🌐 Translations

Translations into any language are welcome. They live in
[`frontend/src/lib/i18n/locales/`](frontend/src/lib/i18n/locales/), one JSON file per
language, with `en.json` as the source.

To improve an existing language, edit its file and open a PR.

To add a new language:

1. Copy `en.json` to `<code>.json`, using the two-letter language code (`de.json`, `pt.json`, …),
   and translate the values.
2. Add the code to `SUPPORTED_LOCALES` in `frontend/src/lib/i18n/locale.ts` (with its name in
   `LOCALE_NAMES`) and in `packages/core/src/setvault_core/locales.py`.
3. Add a `register(...)` line for it in `frontend/src/lib/i18n/index.ts`.
4. Open a PR.

- Keys missing from a locale fall back to English, so partial translations are fine.
- Don't add keys that aren't in `en.json`, and keep every `{placeholder}` and ICU
  `plural`/`select` block intact. `npm run test:unit` checks both.
- Keep badges and hints short; they sit in tight spots.

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

The backend needs Postgres and Redis. Start them as containers (for example `postgres:18-alpine` and `redis:7-alpine`)
and point `DATABASE_URL` and `REDIS_URL` at them. Uploads need tusd, which the all-in-one image bundles;
the rest of the app works without it. `GET /api/health` shows whether the backend is up.

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
browsers ─▶ caddy :1970 ─┬─▶ web (uvicorn)
(bundled mode)           └─▶ tusd /uploads
(external mode: no caddy; uvicorn binds :1970 directly)

 scheduler (rqscheduler) ─▶ Redis 7 ─▶ worker (RQ) · watcher (filesystem events)
                              │
          Postgres 18 ◀───────┴───────▶ ffmpeg + fpcalc
```

- **`apps/web`** — FastAPI + bundled SvelteKit
- **`apps/worker`** — RQ worker (transcode / waveform / enrichment) + `watchdog` watcher; `rqscheduler` runs the periodic jobs as the `scheduler` service
- **`packages/core`** — SQLAlchemy models, services, RQ job entrypoints
- **`packages/providers`** — metadata provider plugins (MusicBrainz / Discogs / AcoustID)
- **`frontend/`** — SvelteKit source (built into the web image); design language in `frontend/design/`
- **`infra/`** — Alembic migrations + Dockerfiles + compose stacks

---

## 🔒 Security

- Argon2 hashing · pure-ASGI CSRF + security-headers middleware · strict CSP/HSTS · HMAC-signed short-TTL URLs
- SSRF allowlist on URL-rip ingest · Redis rate-limiting on login, URL and discovery rips, and search · exact-pinned `yt-dlp`
- `no-new-privileges` on every container · audit log of every state-changing admin action

> **Defense-in-depth:** `yt-dlp` follows redirects without an internal-IP guard, so firewall
> container egress to block the cloud metadata endpoint (`169.254.169.254`) and RFC-1918 / link-local
> ranges. This stops a redirect-based SSRF even if it slips past the host allowlist.

Report security issues privately to the maintainer, not via public GitHub issues.

---

## 📋 Status

Shipped: URL rip, multi-source search, monitored entities, fingerprinting and quality upgrades, the set editor and browse pages;
casting, Subsonic API, smart playlists, and OIDC are on the roadmap. Each phase ships as a PR with
conventional commits driving the CHANGELOG — see [CHANGELOG.md](CHANGELOG.md) for the full history and what's next.

---

## 🤖 AI-assisted disclosure

SetVault is built with substantial help from AI coding assistants (primarily Claude Code). Every change is
reviewed, tested, and shipped by the human maintainer, but the bulk of the code is co-authored with an LLM
(commits carry `Co-Authored-By: Claude ...`).

## 📄 License

GPL-3.0-or-later — see [LICENSE](LICENSE). Free to use, modify, and self-host; distributed modifications stay
GPL-3.0.

## 🙏 Credits

**wavesurfer.js** · **yt-dlp** · **tusd** · **MusicBrainz / Discogs / AcoustID** — and every CI red that got us here.
</content>
