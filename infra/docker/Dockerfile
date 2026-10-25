# syntax=docker/dockerfile:1.7
#
# SetVault — single all-in-one image.
#
# Runs these services under s6-overlay (PID 1):
#   - web          → uvicorn: FastAPI + bundled SvelteKit on :1970
#   - worker       → rq worker: transcode / waveform / enrichment / bulk jobs
#   - watcher      → watchdog-driven WatchFolder ingest
#   - scheduler    → rqscheduler: periodic jobs
#   - tusd         → resumable uploads on 127.0.0.1:8080
#   - caddy, postgres, redis → bundled mode (idle placeholders in external mode)
#
# Multi-arch (linux/amd64 + linux/arm64). Per-arch native deps are
# selected from $TARGETARCH so QEMU builds don't try to install
# amd64 binaries on arm64.

ARG S6_OVERLAY_VERSION=3.2.1.0
# Deno runs yt-dlp's YouTube JS-challenge solver (yt-dlp-ejs) and the bgutil
# PO-token server. BGUTIL_VERSION must match bgutil-ytdlp-pot-provider in
# packages/core/pyproject.toml.
ARG DENO_VERSION=2.9.7
ARG BGUTIL_VERSION=2.0.2

FROM denoland/deno:bin-${DENO_VERSION} AS deno

# ── Frontend stage ──────────────────────────────────────────────────────────
FROM node:26-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json frontend/
RUN cd frontend && npm ci
COPY frontend frontend/
RUN mkdir -p /build/apps/web/src/setvault_web/static
RUN cd frontend && npm run build

# ── Base: native deps + s6-overlay ──────────────────────────────────────────
# bookworm pin matches the audiowaveform deb's boost ABI.
FROM python:3.12-slim-bookworm AS base
ARG TARGETARCH
ARG S6_OVERLAY_VERSION
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

# Apt-installable deps (same on every arch).
RUN apt-get update && apt-get install -y --no-install-recommends \
      ffmpeg libmagic1 libchromaprint-tools tini ca-certificates curl xz-utils \
      tesseract-ocr tzdata \
      libmad0 libid3tag0 libgd3 \
      libboost-program-options1.74.0 libboost-filesystem1.74.0 libboost-regex1.74.0 \
    && rm -rf /var/lib/apt/lists/*

# audiowaveform — BBC publishes per-arch debs.
RUN case "${TARGETARCH}" in \
      amd64) AW_ARCH=amd64 ;; \
      arm64) AW_ARCH=arm64 ;; \
      *) echo "Unsupported TARGETARCH=${TARGETARCH}" >&2 && exit 1 ;; \
    esac && \
    curl -fsSL "https://github.com/bbc/audiowaveform/releases/download/1.10.1/audiowaveform_1.10.1-1-12_${AW_ARCH}.deb" \
      -o /tmp/audiowaveform.deb && \
    dpkg -i /tmp/audiowaveform.deb && \
    rm /tmp/audiowaveform.deb

# PostgreSQL 18 (PGDG apt repo — bookworm default is older), Redis, tusd, Caddy.
# gpg/gnupg must be installed first before we can dearmor the PGDG signing key.
RUN apt-get update && apt-get install -y --no-install-recommends gpg gnupg && \
    rm -rf /var/lib/apt/lists/* && \
    install -d /usr/share/postgresql-common/pgdg && \
    curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
      | gpg --dearmor -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.gpg && \
    echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.gpg] http://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" \
      > /etc/apt/sources.list.d/pgdg.list && \
    apt-get update && apt-get install -y --no-install-recommends \
      postgresql-18 postgresql-client-18 redis-server \
    && rm -rf /var/lib/apt/lists/*

# tusd — pinned release tarball (matches the v2.4 image compose used).
RUN case "${TARGETARCH}" in \
      amd64) TUS_ARCH=amd64 ;; arm64) TUS_ARCH=arm64 ;; \
      *) echo "Unsupported TARGETARCH=${TARGETARCH}" >&2 && exit 1 ;; \
    esac && \
    curl -fsSL "https://github.com/tus/tusd/releases/download/v2.4.0/tusd_linux_${TUS_ARCH}.tar.gz" \
      -o /tmp/tusd.tgz && \
    tar -C /tmp -xzf /tmp/tusd.tgz && \
    install -m 0755 "/tmp/tusd_linux_${TUS_ARCH}/tusd" /usr/local/bin/tusd && \
    rm -rf /tmp/tusd.tgz "/tmp/tusd_linux_${TUS_ARCH}"

# Caddy — pinned GitHub release, verified against the release's published
# SHA-512. (The caddyserver.com build API used before had no timeout and hung
# image builds when it was slow.)
ARG CADDY_VERSION=2.11.7
RUN case "${TARGETARCH}" in \
      amd64) CADDY_ARCH=amd64; CADDY_SHA512=a7a433a1b133efc3c8d10eb0b99d52a24b5ef5c322dc77f5282182b1c0402139ab83f3a99f0c52409df77d20123fb0b523edad8a66d8f5e49136197bf61ef0e7 ;; \
      arm64) CADDY_ARCH=arm64; CADDY_SHA512=3db36ba90c7a6e8dda40ee3dd71fa08844c76b5fb08f61b31e5e78d2ed38e71c51dc7baed875e50d1ca1279196e84302967237386ae87c91ae9f2aaceada682e ;; \
    esac && \
    curl -fsSL --retry 3 --connect-timeout 20 --max-time 300 \
      "https://github.com/caddyserver/caddy/releases/download/v${CADDY_VERSION}/caddy_${CADDY_VERSION}_linux_${CADDY_ARCH}.tar.gz" \
      -o /tmp/caddy.tgz && \
    echo "${CADDY_SHA512}  /tmp/caddy.tgz" | sha512sum -c - && \
    tar -C /tmp -xzf /tmp/caddy.tgz caddy && \
    install -m 0755 /tmp/caddy /usr/local/bin/caddy && \
    rm -f /tmp/caddy.tgz /tmp/caddy

# s6-overlay — process supervisor. Standard LinuxServer-style install.
RUN case "${TARGETARCH}" in \
      amd64) S6_ARCH=x86_64 ;; \
      arm64) S6_ARCH=aarch64 ;; \
    esac && \
    curl -fsSL "https://github.com/just-containers/s6-overlay/releases/download/v${S6_OVERLAY_VERSION}/s6-overlay-noarch.tar.xz" -o /tmp/s6-noarch.tar.xz && \
    curl -fsSL "https://github.com/just-containers/s6-overlay/releases/download/v${S6_OVERLAY_VERSION}/s6-overlay-${S6_ARCH}.tar.xz" -o /tmp/s6-arch.tar.xz && \
    curl -fsSL "https://github.com/just-containers/s6-overlay/releases/download/v${S6_OVERLAY_VERSION}/s6-overlay-symlinks-noarch.tar.xz" -o /tmp/s6-symlinks-noarch.tar.xz && \
    curl -fsSL "https://github.com/just-containers/s6-overlay/releases/download/v${S6_OVERLAY_VERSION}/s6-overlay-symlinks-arch.tar.xz" -o /tmp/s6-symlinks-arch.tar.xz && \
    tar -C / -Jxpf /tmp/s6-noarch.tar.xz && \
    tar -C / -Jxpf /tmp/s6-arch.tar.xz && \
    tar -C / -Jxpf /tmp/s6-symlinks-noarch.tar.xz && \
    tar -C / -Jxpf /tmp/s6-symlinks-arch.tar.xz && \
    rm /tmp/s6-noarch.tar.xz /tmp/s6-arch.tar.xz /tmp/s6-symlinks-noarch.tar.xz /tmp/s6-symlinks-arch.tar.xz

RUN pip install --no-cache-dir uv

COPY --from=deno /deno /usr/local/bin/deno

# ── PO-token server: bgutil's YouTube proof-of-origin token provider ─────────
# Built on the runtime base so the native canvas module matches its glibc.
FROM base AS potserver
ARG BGUTIL_VERSION
ENV DENO_DIR=/opt/bgutil/.deno
RUN mkdir -p /opt/bgutil "${DENO_DIR}" && \
    curl -fsSL --retry 3 --connect-timeout 20 --max-time 300 \
      "https://github.com/Brainicism/bgutil-ytdlp-pot-provider/archive/refs/tags/${BGUTIL_VERSION}.tar.gz" \
      | tar -xz -C /opt/bgutil --strip-components=1 && \
    cd /opt/bgutil/server && \
    deno install --allow-scripts=npm:canvas --frozen

# ── Deps layer ──────────────────────────────────────────────────────────────
FROM base AS deps
WORKDIR /srv
COPY pyproject.toml uv.lock ./
COPY packages/core/pyproject.toml packages/core/pyproject.toml
COPY packages/providers/pyproject.toml packages/providers/pyproject.toml
COPY packages/ingest_sources/pyproject.toml packages/ingest_sources/pyproject.toml
COPY apps/web/pyproject.toml apps/web/pyproject.toml
COPY apps/worker/pyproject.toml apps/worker/pyproject.toml
RUN uv sync --frozen --no-install-project || uv sync --no-install-project

# ── Runtime ─────────────────────────────────────────────────────────────────
FROM deps AS runtime
COPY packages/core packages/core
COPY packages/providers packages/providers
COPY packages/ingest_sources packages/ingest_sources
COPY apps/web apps/web
COPY apps/worker apps/worker
COPY alembic.ini ./
COPY infra/migrations infra/migrations
COPY --from=frontend /build/apps/web/src/setvault_web/static apps/web/src/setvault_web/static
RUN uv sync --no-dev

COPY --from=potserver /opt/bgutil/server /opt/bgutil/server
COPY --from=potserver /opt/bgutil/.deno /opt/bgutil/.deno

# s6 services + container init scripts.
COPY infra/docker/s6-rc.d /etc/s6-overlay/s6-rc.d
COPY infra/docker/cont-init.d /etc/cont-init.d
RUN chmod +x /etc/cont-init.d/* /etc/s6-overlay/s6-rc.d/*/run /etc/s6-overlay/s6-rc.d/*/up 2>/dev/null || true

COPY infra/docker/lib/ /etc/setvault/
COPY infra/docker/Caddyfile /etc/setvault/Caddyfile
RUN chmod +x /etc/setvault/*.sh

ENV PATH="/srv/.venv/bin:${PATH}"

# Halt the container if any cont-init script (00-mode/01-defaults/02-validate)
# or s6-rc oneshot (init-db) fails — otherwise s6 continues to the longruns and
# the required-env / SECRET_KEY gates and migrations would be merely cosmetic.
ENV S6_BEHAVIOUR_IF_STAGE2_FAILS=2

# Defaults for the noob-friendly compose path. DATABASE_URL is left
# unset so cont-init can synthesize it from POSTGRES_PASSWORD; override
# directly if you point at an external postgres. The SETVAULT_*_PATH data
# dirs are deliberately NOT preset here: cont-init.d/00-mode resolves them per
# mode (bundled => /data/<x>, or a mounted /srv/<x>; external => /srv/<x>), and
# an image-level default would mask the bundled /data defaults.
ENV POSTGRES_USER=setvault \
    POSTGRES_DB=setvault \
    POSTGRES_PORT=5432 \
    PUID=1000 \
    PGID=1000

WORKDIR /srv/apps/web

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:1970/api/health').read()"

EXPOSE 1970

ENTRYPOINT ["/init"]
