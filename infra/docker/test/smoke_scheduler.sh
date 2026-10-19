#!/usr/bin/env bash
# Smoke for periodic jobs: the rq-scheduler service must be moving registered
# entries onto the queue, so a worker actually runs them.
#
# Signal: the media-root health check (every 5 minutes, first run due at worker
# boot) stamps last_health_check_at on every MediaRoot. init-db seeds a default
# root, and GET /api/admin/health exposes the stamp, so a non-null value proves
# the whole chain ran: entrypoint registration -> rqscheduler poll -> default
# queue -> worker. It is fully offline (the github version poll needs the
# internet; recycle-bin purge and the others leave no first-run trace). Redis
# internals would be more brittle, and a stamp that is null at boot can only
# be set by the job.
#
# Run it early (right after the health wait): the job should fire within about
# one poll interval (30 s) of the worker booting.
#
# Usage: CONTAINER=sv BASE=http://localhost:1970 infra/docker/test/smoke_scheduler.sh
set -euo pipefail
# shellcheck source=smoke_lib.sh
. "$(dirname "$0")/smoke_lib.sh"

DEADLINE="${SCHEDULER_TIMEOUT:-120}"

echo "--- sign in"
sign_in

echo "--- waiting up to ${DEADLINE}s for a scheduled media-root health check to run"
for _ in $(seq 1 $((DEADLINE / 3))); do
  STAMPED="$(api GET /api/admin/health | json \
    "sum(1 for r in d['storage_roots'] if r['last_health_check_at'])")"
  if [ "${STAMPED}" -ge 1 ]; then
    echo "stamped roots: ${STAMPED}"
    echo "scheduler smoke OK"
    exit 0
  fi
  sleep 3
done
echo "no media root was health-checked: periodic jobs are not running"
docker exec "${CONTAINER}" sh -c 'ls /run/service 2>/dev/null; s6-svstat /run/service/scheduler 2>/dev/null' || true
exit 1
