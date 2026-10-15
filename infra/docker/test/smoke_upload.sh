#!/usr/bin/env bash
# End-to-end upload smoke against a running bundled container.
#
# Signs in (creating the first admin), tus-uploads a short generated FLAC
# through Caddy -> tusd -> post-finish hook, then waits for the worker pipeline
# (probe -> fingerprint -> transcode -> normalize -> waveform -> ready) to
# publish the set and checks loudness, the Opus stream and the waveform.
#
# Usage: CONTAINER=sv BASE=http://localhost:1970 infra/docker/test/smoke_upload.sh
set -euo pipefail
# shellcheck source=smoke_lib.sh
. "$(dirname "$0")/smoke_lib.sh"

CLIP="${WORK}/smoke.flac"

echo "--- generating clip inside the container (uses its ffmpeg)"
docker exec "${CONTAINER}" ffmpeg -hide_banner -loglevel error -y \
  -f lavfi -i "sine=frequency=440:duration=5" -ac 2 /tmp/smoke.flac
docker exec "${CONTAINER}" cat /tmp/smoke.flac >"${CLIP}"
SIZE="$(wc -c <"${CLIP}" | tr -d ' ')"
echo "clip: ${SIZE} bytes"

echo "--- sign in"
sign_in

echo "--- tus create"
NAME_B64="$(printf 'smoke.flac' | base64)"
LOCATION="$(curl -fsS -b "${JAR}" -o /dev/null -D - -X POST \
  -H 'Tus-Resumable: 1.0.0' \
  -H "Upload-Length: ${SIZE}" \
  -H "Upload-Metadata: filename ${NAME_B64}" \
  "${BASE}/uploads/" | tr -d '\r' | awk 'tolower($1)=="location:"{print $2}')"
test -n "${LOCATION}" || { echo "tus create returned no Location"; exit 1; }
case "${LOCATION}" in http*) ;; *) LOCATION="${BASE}${LOCATION}" ;; esac
echo "upload: ${LOCATION}"

echo "--- tus patch"
curl -fsS -b "${JAR}" -o /dev/null -X PATCH \
  -H 'Tus-Resumable: 1.0.0' \
  -H 'Upload-Offset: 0' \
  -H 'Content-Type: application/offset+octet-stream' \
  --data-binary "@${CLIP}" \
  "${LOCATION}"

SLUG="$(wait_for_set "smoke.flac")"
assert_published_set "${SLUG}"

echo "upload smoke OK"
