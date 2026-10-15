#!/usr/bin/env bash
# End-to-end watch-folder smoke against a running bundled container.
#
# Registers a watch folder under the container's watch path, waits for the
# watcher service to subscribe to it, then drops a generated FLAC whose name
# matches the "date - artist - title" pattern. The watcher enqueues
# watch_folder_ingest, which places the file and chains the media pipeline;
# the published set gets the same checks as an upload.
#
# Usage: CONTAINER=sv BASE=http://localhost:1970 infra/docker/test/smoke_watch_folder.sh
set -euo pipefail
# shellcheck source=smoke_lib.sh
. "$(dirname "$0")/smoke_lib.sh"

TITLE="Watch Folder Smoke"
FILE="2026-01-15 - Smoke Artist - ${TITLE}.flac"
WATCH_DIR="$(sv_env SETVAULT_WATCH_FOLDERS_PATH)/smoke"
RUN_AS="$(sv_user)"

echo "--- sign in"
sign_in

echo "--- watch dir ${WATCH_DIR} (owned by the app uid ${RUN_AS})"
docker exec -u "${RUN_AS}" "${CONTAINER}" mkdir -p "${WATCH_DIR}"

ROOT_ID="$(api GET /api/media-roots \
  | json "next(r['id'] for r in d['items'] if r['default_for_ingest'])")"
WF_ID="$(api POST /api/admin/watch-folders \
  -d "{\"name\":\"smoke\",\"host_path\":\"${WATCH_DIR}\",\"target_media_root_id\":\"${ROOT_ID}\"}" \
  | json "d['id']")"
echo "watch folder: ${WF_ID} -> root ${ROOT_ID}"

# The watcher re-reads enabled folders every 30 s; a file dropped before it
# subscribes would never raise an event.
echo "--- waiting for the watcher to subscribe"
for _ in $(seq 1 30); do
  if docker logs "${CONTAINER}" 2>&1 | grep -q "watching ${WF_ID}"; then break; fi
  sleep 2
done
docker logs "${CONTAINER}" 2>&1 | grep -q "watching ${WF_ID}" \
  || { echo "watcher never subscribed to ${WATCH_DIR}"; exit 1; }

echo "--- dropping '${FILE}' (written as .tmp, then renamed in)"
docker exec -u "${RUN_AS}" "${CONTAINER}" ffmpeg -hide_banner -loglevel error -y \
  -f lavfi -i "sine=frequency=660:duration=5" -ac 2 -f flac "${WATCH_DIR}/incoming.tmp"
docker exec -u "${RUN_AS}" "${CONTAINER}" mv "${WATCH_DIR}/incoming.tmp" "${WATCH_DIR}/${FILE}"

SLUG="$(wait_for_set "${TITLE}")"
assert_published_set "${SLUG}"

echo "watch-folder smoke OK"
