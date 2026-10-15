#!/usr/bin/env bash
# Smoke for the one-off loudness backfill against a running bundled container.
#
# Run after an ingest smoke has published at least one set: rewinds that set's
# normalized_lufs to the bogus -70.0 the old ebur128 parser stored, triggers
# POST /api/admin/maintenance/remeasure-loudness, and waits for the worker to
# write a real value back.
#
# Usage: CONTAINER=sv BASE=http://localhost:1970 infra/docker/test/smoke_loudness_backfill.sh
set -euo pipefail
# shellcheck source=smoke_lib.sh
. "$(dirname "$0")/smoke_lib.sh"

echo "--- sign in"
sign_in

SLUG="$(api GET /api/sets | json "d['items'][0]['slug']")"
echo "--- rewinding ${SLUG} to -70.0 LUFS"
docker exec -e PGPASSWORD="$(sv_env POSTGRES_PASSWORD)" "${CONTAINER}" \
  psql -h 127.0.0.1 -U "$(sv_env POSTGRES_USER)" -d "$(sv_env POSTGRES_DB)" -v ON_ERROR_STOP=1 \
  -qc "UPDATE live_sets SET normalized_lufs = -70.0 WHERE slug = '${SLUG}'"

echo "--- trigger backfill"
api POST /api/admin/maintenance/remeasure-loudness | json "d['candidates']" \
  | { read -r n; echo "candidates: ${n}"; test "${n}" -ge 1; }

echo "--- waiting up to ${TIMEOUT}s for a re-measured value"
for _ in $(seq 1 $((TIMEOUT / 3))); do
  LUFS="$(api GET "/api/sets/${SLUG}" | json "d['normalized_lufs']")"
  if python3 -c "import sys; v=float(sys.argv[1]); sys.exit(0 if -40 < v < 0 and v != -70 else 1)" \
      "${LUFS}"; then
    echo "lufs: ${LUFS}"
    echo "loudness backfill smoke OK"
    exit 0
  fi
  sleep 3
done
echo "backfill never re-measured ${SLUG} (still ${LUFS})"
exit 1
