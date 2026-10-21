#!/usr/bin/env bash
# Container-recreate smoke for the bundled image.
#
# Boots setvault:ci on a named volume with no SECRET_KEY / POSTGRES_PASSWORD,
# creates the admin, uploads a clip and checks the media lands in /data (not the
# container layer under /srv) and that .secrets is root 0600. Then it dirties
# .secrets with a CRLF comment and a blank line, removes the container and runs
# the same command again: the old session cookie must still work (SECRET_KEY was
# persisted, not regenerated) and the set must still stream. Last, it seeds a
# legacy media root at /srv/media and restarts; the boot repair job must repoint
# it at /data/media.
#
# Owns the `sv` container and `svdata` volume: removes any leftovers first, and
# removes both again on success (set SMOKE_KEEP=1 to keep them). On failure it
# prints `docker logs sv` and leaves the container for inspection.
#
# Usage: IMAGE=setvault:ci BASE=http://localhost:1970 infra/docker/test/smoke_recreate.sh
set -euo pipefail
export CONTAINER=sv
# shellcheck source=smoke_lib.sh
. "$(dirname "$0")/smoke_lib.sh"

IMAGE="${IMAGE:-setvault:ci}"
VOLUME=svdata
JAR="${WORK}/recreate.cookies"
CLIP="${WORK}/smoke-recreate.flac"

on_exit() {
  local rc=$?
  if [ "${rc}" -ne 0 ]; then
    echo "!!! recreate smoke failed (exit ${rc}); container logs follow" >&2
    docker logs "${CONTAINER}" 2>&1 || true
  elif [ "${SMOKE_KEEP:-0}" != "1" ]; then
    docker rm -f "${CONTAINER}" >/dev/null 2>&1 || true
    docker volume rm "${VOLUME}" >/dev/null 2>&1 || true
  fi
  rm -rf "${WORK}"
  exit "${rc}"
}
trap on_exit EXIT

start() {
  docker run -d --name "${CONTAINER}" -v "${VOLUME}:/data" -p 1970:1970 "${IMAGE}" >/dev/null
}

wait_health() {
  echo "--- waiting for ${BASE}/api/health"
  for _ in $(seq 1 $((TIMEOUT / 3))); do
    if curl -fsS -o /dev/null "${BASE}/api/health" 2>/dev/null; then echo "healthy"; return 0; fi
    sleep 3
  done
  echo "health never came up" >&2
  return 1
}

psql_sv() {
  docker exec -e PGPASSWORD="$(sv_env POSTGRES_PASSWORD)" "${CONTAINER}" \
    psql -h 127.0.0.1 -U "$(sv_env POSTGRES_USER)" -d "$(sv_env POSTGRES_DB)" \
    -v ON_ERROR_STOP=1 -qtAc "$1"
}

echo "--- clean slate"
docker rm -f "${CONTAINER}" >/dev/null 2>&1 || true
docker volume rm "${VOLUME}" >/dev/null 2>&1 || true
docker volume create "${VOLUME}" >/dev/null

echo "--- first boot (no SECRET_KEY, no POSTGRES_PASSWORD)"
start
wait_health

echo "--- sign in"
sign_in

echo "--- upload a clip and wait for it to publish"
docker exec "${CONTAINER}" ffmpeg -hide_banner -loglevel error -y \
  -f lavfi -i "sine=frequency=440:duration=5" -ac 2 /tmp/smoke-recreate.flac
docker exec "${CONTAINER}" cat /tmp/smoke-recreate.flac >"${CLIP}"
SIZE="$(wc -c <"${CLIP}" | tr -d ' ')"
NAME_B64="$(printf 'smoke-recreate.flac' | base64 | tr -d '\n')"
LOCATION="$(curl -fsS -b "${JAR}" -o /dev/null -D - -X POST \
  -H 'Tus-Resumable: 1.0.0' \
  -H "Upload-Length: ${SIZE}" \
  -H "Upload-Metadata: filename ${NAME_B64}" \
  "${BASE}/uploads/" | tr -d '\r' | awk 'tolower($1)=="location:"{print $2}')"
test -n "${LOCATION}" || { echo "tus create returned no Location"; exit 1; }
case "${LOCATION}" in http*) ;; *) LOCATION="${BASE}${LOCATION}" ;; esac
curl -fsS -b "${JAR}" -o /dev/null -X PATCH \
  -H 'Tus-Resumable: 1.0.0' \
  -H 'Upload-Offset: 0' \
  -H 'Content-Type: application/offset+octet-stream' \
  --data-binary "@${CLIP}" \
  "${LOCATION}"
SLUG="$(wait_for_set "smoke-recreate.flac")"
echo "published: ${SLUG}"

echo "--- media is on the volume, not in the container layer"
MEDIA="$(docker exec "${CONTAINER}" sh -c 'ls -A /data/media')"
test -n "${MEDIA}" || { echo "/data/media is empty"; exit 1; }
echo "/data/media: ${MEDIA}"
SRV="$(docker exec "${CONTAINER}" sh -c 'ls -A /srv/media 2>/dev/null | wc -l' | tr -d ' ')"
test "${SRV}" = "0" || { echo "/srv/media has ${SRV} entries"; exit 1; }
echo "/srv/media: empty or absent"

echo "--- .secrets is root 0600"
PERM="$(docker exec "${CONTAINER}" stat -c '%U %a' /data/config/.secrets)"
test "${PERM}" = "root 600" || { echo ".secrets is '${PERM}', want 'root 600'"; exit 1; }
echo ".secrets: ${PERM}"

echo "--- dirty .secrets with a CRLF comment and a blank line"
docker exec "${CONTAINER}" sh -c "printf '# comment\r\n\n' >> /data/config/.secrets"

echo "--- recreate the container with the same command"
docker rm -f "${CONTAINER}" >/dev/null
start
wait_health

echo "--- the old session still works (SECRET_KEY persisted)"
CODE="$(curl -sS -b "${JAR}" -o /dev/null -w '%{http_code}' "${BASE}/api/auth/me")"
echo "/api/auth/me -> ${CODE}"
test "${CODE}" = "200" || { echo "session did not survive the recreate"; exit 1; }

echo "--- the set still streams"
CODE="$(curl -sS -b "${JAR}" -o /dev/null -w '%{http_code}' "${BASE}/api/sets/${SLUG}/stream")"
echo "/api/sets/${SLUG}/stream -> ${CODE}"
case "${CODE}" in 200|206) ;; *) echo "stream failed after recreate"; exit 1 ;; esac

echo "--- seed a legacy media root at /srv/media and restart"
psql_sv "INSERT INTO media_roots (id, name, host_path, enabled, default_for_ingest, last_health_status, created_at, updated_at)
         VALUES (gen_random_uuid(), 'legacy-smoke', '/srv/media', false, false, 'unknown', now(), now())"
docker restart "${CONTAINER}" >/dev/null
wait_health

HOST_PATH=""
for _ in $(seq 1 20); do
  HOST_PATH="$(psql_sv "SELECT host_path FROM media_roots WHERE name = 'legacy-smoke'" 2>/dev/null || true)"
  [ "${HOST_PATH}" = "/data/media" ] && break
  sleep 3
done
echo "legacy-smoke host_path: ${HOST_PATH}"
test "${HOST_PATH}" = "/data/media" || { echo "repair job did not repoint the legacy root"; exit 1; }

echo "recreate smoke OK"
