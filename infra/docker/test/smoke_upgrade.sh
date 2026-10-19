#!/usr/bin/env bash
# End-to-end quality-upgrade smoke against a running bundled container.
#
# Uploads a 30 s noise clip as MP3 128k and waits for it to publish, then
# uploads the same audio as FLAC. The fingerprint matches the first set and
# FLAC (lossless) beats MP3 128 (ok), and the same admin owns both, so the
# ingest decision swaps the audio into the existing set instead of publishing
# a second one. Asserts, via the API, that the first set's slug survives with a
# FLAC quality label, that no second set was published, and that the old MP3
# copy is in the recycle bin.
#
# Usage: CONTAINER=sv BASE=http://localhost:1970 infra/docker/test/smoke_upgrade.sh
set -euo pipefail
# shellcheck source=smoke_lib.sh
. "$(dirname "$0")/smoke_lib.sh"

MP3="${WORK}/smoke-upgrade.mp3"
FLAC="${WORK}/smoke-upgrade-better.flac"

echo "--- generating one 30 s noise source and encoding it twice (the container's ffmpeg)"
# Broadband noise plus a tone: a pure sine has too little spectral content for
# chromaprint, and the fuzzy matcher needs about 20 s of audio.
docker exec "${CONTAINER}" sh -c '
  set -e
  ffmpeg -hide_banner -loglevel error -y \
    -f lavfi -i "anoisesrc=d=30:c=pink:r=44100:a=0.5" \
    -f lavfi -i "sine=frequency=440:duration=30:sample_rate=44100" \
    -filter_complex "[0:a][1:a]amix=inputs=2:duration=first,aformat=channel_layouts=stereo[a]" \
    -map "[a]" /tmp/upgrade-src.wav
  ffmpeg -hide_banner -loglevel error -y -i /tmp/upgrade-src.wav -c:a libmp3lame -b:a 128k /tmp/smoke-upgrade.mp3
  ffmpeg -hide_banner -loglevel error -y -i /tmp/upgrade-src.wav -c:a flac /tmp/smoke-upgrade-better.flac
'
docker exec "${CONTAINER}" cat /tmp/smoke-upgrade.mp3 >"${MP3}"
docker exec "${CONTAINER}" cat /tmp/smoke-upgrade-better.flac >"${FLAC}"
echo "mp3: $(wc -c <"${MP3}" | tr -d ' ') bytes, flac: $(wc -c <"${FLAC}" | tr -d ' ') bytes"

echo "--- sign in"
sign_in

# tus_upload FILE NAME: create + patch through Caddy -> tusd -> post-finish hook.
tus_upload() {
  local file="$1" name="$2" size name_b64 location
  size="$(wc -c <"${file}" | tr -d ' ')"
  name_b64="$(printf '%s' "${name}" | base64 | tr -d '\n')"
  location="$(curl -fsS -b "${JAR}" -o /dev/null -D - -X POST \
    -H 'Tus-Resumable: 1.0.0' \
    -H "Upload-Length: ${size}" \
    -H "Upload-Metadata: filename ${name_b64}" \
    "${BASE}/uploads/" | tr -d '\r' | awk 'tolower($1)=="location:"{print $2}')"
  test -n "${location}" || { echo "tus create returned no Location"; return 1; }
  case "${location}" in http*) ;; *) location="${BASE}${location}" ;; esac
  curl -fsS -b "${JAR}" -o /dev/null -X PATCH \
    -H 'Tus-Resumable: 1.0.0' \
    -H 'Upload-Offset: 0' \
    -H 'Content-Type: application/offset+octet-stream' \
    --data-binary "@${file}" \
    "${location}"
}

echo "--- upload the MP3 128k copy and wait for it to publish"
tus_upload "${MP3}" "smoke-upgrade.mp3"
SLUG="$(wait_for_set "smoke-upgrade.mp3")"
assert_published_set "${SLUG}"

echo "--- the first copy is labelled MP3"
LABEL="$(api GET "/api/sets/${SLUG}" | json "(d.get('quality') or {}).get('label', '')")"
echo "quality: ${LABEL}"
case "${LABEL}" in MP3*) ;; *) echo "expected an MP3 label, got '${LABEL}'"; exit 1 ;; esac

echo "--- upload the same audio as FLAC; ingest should upgrade the first set in place"
tus_upload "${FLAC}" "smoke-upgrade-better.flac"
for _ in $(seq 1 $((TIMEOUT / 3))); do
  LABEL="$(api GET "/api/sets/${SLUG}" | json "(d.get('quality') or {}).get('label', '')")"
  case "${LABEL}" in FLAC*) break ;; esac
  sleep 3
done
echo "quality: ${LABEL}"
case "${LABEL}" in FLAC*) ;; *) echo "set ${SLUG} was never upgraded to FLAC (label '${LABEL}')"; exit 1 ;; esac

echo "--- the library still holds exactly one set from this pair"
api GET /api/sets | python3 -c "
import json, sys
d = json.load(sys.stdin)
titles = [i['title'] for i in d['items'] if i['title'].startswith('smoke-upgrade')]
print('published titles:', titles)
sys.exit(0 if titles == ['smoke-upgrade.mp3'] else 1)
" || { echo "expected one published smoke-upgrade set"; exit 1; }

echo "--- the old MP3 copy is in the recycle bin"
api GET /api/admin/recycle | python3 -c "
import json, sys
d = json.load(sys.stdin)
hits = [i for i in d['items'] if i['title'].startswith('smoke-upgrade.mp3') and i['purge_after_at']]
print('recycled:', [(i['slug'], i['title']) for i in hits])
sys.exit(0 if len(hits) == 1 and hits[0]['slug'] != '${SLUG}' else 1)
" || { echo "expected the replaced copy in the recycle bin"; exit 1; }

echo "--- the upgraded set still plays (stream + waveform follow the new audio)"
assert_published_set "${SLUG}"

echo "upgrade smoke OK"
