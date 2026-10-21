#!/usr/bin/env bash
# Bring the database to a migrated state, both modes. Run by the init-db
# s6 oneshot (after the postgres longrun is "up"). Idempotent.
set -e
PGBIN=/usr/lib/postgresql/18/bin

# Embedded first boot: wait for the just-started local server, then ensure the
# database + role password exist (via the local trust socket). External mode
# skips this — readiness there is handled by compose's depends_on healthcheck
# (or the user's own server) plus alembic's retry below; POSTGRES_HOST may be
# unset when only DATABASE_URL is supplied, so pg_isready can't be relied on.
if [ "${SETVAULT_PG_EMBEDDED}" = "1" ]; then
  attempts=0; max=60
  until "${PGBIN}/pg_isready" -h "${POSTGRES_HOST}" -p "${POSTGRES_PORT:-5432}" -q; do
    attempts=$((attempts + 1))
    if [ "${attempts}" -ge "${max}" ]; then
      echo "[setvault] embedded postgres not ready after ${max} tries; bailing" >&2
      exit 1
    fi
    sleep 2
  done

  # Connect as the bootstrap superuser `setvault` (initdb -U setvault, see
  # s6-rc.d/postgres/run) and ensure the app role ${POSTGRES_USER} exists as a
  # LOGIN role, owns ${POSTGRES_DB} when we create it, and has the password.
  # Everything goes via stdin: psql performs :'x' / :"x" substitution on
  # stdin/-f (but NOT with -c, and never inside $$ bodies — hence the
  # SELECT format(...) \gexec form). -v passes values out-of-band and the
  # quoting forms escape them, so special characters can't break the statement
  # or inject SQL. CREATE DATABASE can't run in a transaction; \gexec runs each
  # generated statement on its own, in autocommit.
  s6-setuidgid "${PUID:-1000}:${PGID:-1000}" \
    "${PGBIN}/psql" -h /tmp -U setvault -d postgres -v ON_ERROR_STOP=1 -q \
    -v role="${POSTGRES_USER:-setvault}" \
    -v db="${POSTGRES_DB:-setvault}" \
    -v pw="${POSTGRES_PASSWORD:-setvault}" <<'PWSQL'
SELECT format('CREATE ROLE %I LOGIN', :'role')
  WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = :'role') \gexec
SELECT format('CREATE DATABASE %I OWNER %I', :'db', :'role')
  WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = :'db') \gexec
ALTER USER :"role" PASSWORD :'pw';
PWSQL
fi

# 3) Migrations (both modes).
cd /srv
attempts=0; max=30
until s6-setuidgid "${PUID:-1000}:${PGID:-1000}" /srv/.venv/bin/alembic upgrade head; do
  attempts=$((attempts + 1))
  if [ "${attempts}" -ge "${max}" ]; then
    echo "[setvault] alembic failed after ${max} tries; bailing" >&2
    exit 1
  fi
  echo "[setvault] alembic retry ${attempts}/${max}" >&2
  sleep 2
done
echo "[setvault] migrations up-to-date" >&2

# Repoint legacy /srv paths (old images) at the /data layout; non-fatal.
s6-setuidgid "${PUID:-1000}:${PGID:-1000}" \
  /srv/.venv/bin/python -m setvault_core.jobs.repair_legacy_paths \
  || echo "[setvault] legacy path repair skipped (non-fatal)" >&2

# 4) Seed the default media root from the mounted storage folder (both modes).
# Radarr/Sonarr style: the volume bound at ${SETVAULT_MEDIA_PATH} is the library
# and the app uses it with no Settings step. Idempotent — only seeds when no
# media root exists yet, so an admin's own roots are never overridden.
s6-setuidgid "${PUID:-1000}:${PGID:-1000}" \
  /srv/.venv/bin/python -m setvault_core.jobs.seed_media_root \
  || echo "[setvault] default media-root seed skipped (non-fatal)" >&2
