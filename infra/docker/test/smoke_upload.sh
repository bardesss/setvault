#!/usr/bin/env bash
# End-to-end upload smoke against a running bundled container.
#
# Creates the first admin, tus-uploads a short generated FLAC through Caddy ->
# tusd -> post-finish hook, then waits for the worker pipeline (probe ->
# fingerprint -> transcode -> normalize -> waveform -> ready) to publish the
# set and checks the Opus stream + waveform are served.
#
# Usage: CONTAINER=sv BASE=http://localhost:1970 infra/docker/test/smoke_upload.sh
set -euo pipefail

BASE="${BASE:-http://localhost:1970}"
CONTAINER="${CONTAINER:-sv}"
TIMEOUT="${TIMEOUT:-240}"
WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT
JAR="${WORK}/cookies"
CLIP="${WORK}/smoke.flac"

json() { python3 -c "import json,sys; d=json.load(sys.stdin); print($1)"; }

echo "--- generating clip inside the container (uses its ffmpeg)"
docker exec "${CONTAINER}" ffmpeg -hide_banner -loglevel error -y \
  -f lavfi -i "sine=frequency=440:duration=5" -ac 2 /tmp/smoke.flac
docker exec "${CONTAINER}" cat /tmp/smoke.flac >"${CLIP}"
SIZE="$(wc -c <"${CLIP}" | tr -d ' ')"
echo "clip: ${SIZE} bytes"

echo "--- first-run admin"
curl -fsS -c "${JAR}" -H 'Content-Type: application/json' \
  -d '{"email":"smoke@example.com","password":"smoke-password-123"}' \
  "${BASE}/api/setup" >/dev/null

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

echo "--- waiting up to ${TIMEOUT}s for the pipeline to publish the set"
SLUG=""
for _ in $(seq 1 $((TIMEOUT / 3))); do
  SLUG="$(curl -fsS -b "${JAR}" "${BASE}/api/sets" \
    | json "d['items'][0]['slug'] if d['total'] else ''")"
  if [ -n "${SLUG}" ]; then break; fi
  sleep 3
done
test -n "${SLUG}" || { echo "set never published (pipeline failed or stalled)"; exit 1; }
echo "published: ${SLUG}"

echo "--- loudness measured (a -20 dBFS sine is ~-20 LUFS; -70 means a parse miss)"
curl -fsS -b "${JAR}" "${BASE}/api/sets/${SLUG}" \
  | json "d['normalized_lufs']" | { read -r lufs; echo "lufs: ${lufs}"; \
    python3 -c "import sys; v=float(sys.argv[1]); sys.exit(0 if -40 < v < 0 else 1)" "${lufs}"; }

echo "--- stream is Opus"
curl -fsS -b "${JAR}" -o "${WORK}/stream" "${BASE}/api/sets/${SLUG}/stream"
test "$(head -c 4 "${WORK}/stream")" = "OggS" || { echo "stream is not Ogg/Opus"; exit 1; }
echo "stream: $(wc -c <"${WORK}/stream" | tr -d ' ') bytes"

echo "--- waveform peaks"
curl -fsS -b "${JAR}" "${BASE}/api/sets/${SLUG}/waveform" \
  | json "len(d['data'])" | { read -r n; test "${n}" -gt 0; echo "peaks: ${n}"; }

echo "upload smoke OK"
