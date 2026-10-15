#!/usr/bin/env bash
# End-to-end URL-rip smoke against a running bundled container, fully offline.
#
# The rip path only accepts allowlisted platforms (SSRF gate), so the smoke
# points a *.bandcamp.com name at 127.0.0.1 inside the container and serves a
# generated WAV from a throwaway HTTP server there. The non-default port keeps
# yt-dlp's Bandcamp extractors from matching, so its generic extractor fetches
# the file directly: submit_rip's probe, the worker's download, then
# transcode -> normalize -> waveform -> ready, with no outbound network.
#
# Usage: CONTAINER=sv BASE=http://localhost:1970 infra/docker/test/smoke_url_rip.sh
set -euo pipefail
# shellcheck source=smoke_lib.sh
. "$(dirname "$0")/smoke_lib.sh"

RIP_HOST="setvault-smoke.bandcamp.com"
RIP_PORT=18080
SRV_DIR=/tmp/sv-rip-smoke
URL="http://${RIP_HOST}:${RIP_PORT}/rip-smoke.wav"

echo "--- ${RIP_HOST} -> 127.0.0.1 inside the container"
docker exec -u 0 "${CONTAINER}" sh -c \
  "grep -q ' ${RIP_HOST}\$' /etc/hosts || echo '127.0.0.1 ${RIP_HOST}' >> /etc/hosts"

echo "--- serving a generated WAV on :${RIP_PORT}"
docker exec "${CONTAINER}" mkdir -p "${SRV_DIR}"
docker exec "${CONTAINER}" ffmpeg -hide_banner -loglevel error -y \
  -f lavfi -i "sine=frequency=880:duration=5" -ac 2 "${SRV_DIR}/rip-smoke.wav"
docker exec -d "${CONTAINER}" python -m http.server "${RIP_PORT}" \
  --bind 127.0.0.1 --directory "${SRV_DIR}"
for _ in $(seq 1 20); do
  if docker exec "${CONTAINER}" python -c \
      "import urllib.request as u; u.urlopen('${URL}', timeout=2)" 2>/dev/null; then
    break
  fi
  sleep 1
done

echo "--- sign in"
sign_in

echo "--- submit ${URL}"
JOB_ID="$(api POST /api/sets/url-rip -d "{\"url\":\"${URL}\"}" | json "d['id']")"
echo "rip job: ${JOB_ID}"

echo "--- waiting up to ${TIMEOUT}s for the rip job to finish"
STATUS=""
for _ in $(seq 1 $((TIMEOUT / 3))); do
  STATUS="$(api GET /api/me/rip-jobs | JOB_ID="${JOB_ID}" python3 -c \
    "import json,os,sys; d=json.load(sys.stdin); j=next(i for i in d['items'] if i['id']==os.environ['JOB_ID']); print(j['status'], j['live_set_slug'] or '-', j['error_text'] or '')")"
  case "${STATUS}" in ready*|failed*) break ;; esac
  sleep 3
done
echo "rip job: ${STATUS}"
case "${STATUS}" in
  ready*) ;;
  *) echo "rip did not finish ready"; exit 1 ;;
esac

SLUG="$(echo "${STATUS}" | awk '{print $2}')"
assert_published_set "${SLUG}"

echo "url-rip smoke OK"
