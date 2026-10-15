# Shared helpers for the AIO smoke scripts. Source it; don't run it.
#
# Expects CONTAINER (bundled container name) and BASE (its URL). Every script
# signs in as the same admin, so they can run in any order against one
# container: the first one through creates the admin via first-run setup.
# The session cookie jar persists across scripts (SMOKE_JAR) because setup and
# login share a 5-per-minute per-IP auth limit.
set -euo pipefail

BASE="${BASE:-http://localhost:1970}"
CONTAINER="${CONTAINER:-sv}"
TIMEOUT="${TIMEOUT:-240}"
WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT
JAR="${SMOKE_JAR:-${TMPDIR:-/tmp}/setvault-smoke-${CONTAINER}.cookies}"
ADMIN_JSON='{"email":"smoke@example.com","password":"smoke-password-123"}'

json() { python3 -c "import json,sys; d=json.load(sys.stdin); print($1)"; }

# Value of an env var as the container's s6 services see it.
sv_env() { docker exec "${CONTAINER}" cat "/run/s6/container_environment/$1"; }

# Runtime uid:gid of the app services (they drop privileges via s6-setuidgid).
sv_user() { echo "$(sv_env PUID 2>/dev/null || echo 1000):$(sv_env PGID 2>/dev/null || echo 1000)"; }

sign_in() {
  local code
  if [ -s "${JAR}" ] && curl -fsS -b "${JAR}" -o /dev/null "${BASE}/api/auth/me" 2>/dev/null; then
    echo "reusing the existing admin session"
    return 0
  fi
  code="$(curl -sS -c "${JAR}" -o /dev/null -w '%{http_code}' \
    -H 'Content-Type: application/json' -d "${ADMIN_JSON}" "${BASE}/api/setup")"
  case "${code}" in
    2*) echo "first-run admin created" ;;
    *) curl -fsS -c "${JAR}" -o /dev/null -H 'Content-Type: application/json' \
         -d "${ADMIN_JSON}" "${BASE}/api/auth/login"
       echo "signed in as existing admin" ;;
  esac
}

# Authenticated JSON call; mutating methods carry the double-submit CSRF token.
api() {
  local method="$1" path="$2"; shift 2
  local csrf
  csrf="$(awk '$6=="csrf_token"{print $7}' "${JAR}" | tail -1)"
  curl -fsS -b "${JAR}" -c "${JAR}" -X "${method}" \
    -H 'Content-Type: application/json' -H "X-CSRF-Token: ${csrf}" \
    "$@" "${BASE}${path}"
}

# Prints the slug of the published set titled $1 once it appears.
wait_for_set() {
  local title="$1" slug=""
  echo "--- waiting up to ${TIMEOUT}s for '${title}' to publish" >&2
  for _ in $(seq 1 $((TIMEOUT / 3))); do
    slug="$(api GET /api/sets | TITLE="${title}" python3 -c \
      "import json,os,sys; d=json.load(sys.stdin); print(next((i['slug'] for i in d['items'] if i['title']==os.environ['TITLE']), ''))")"
    if [ -n "${slug}" ]; then echo "${slug}"; return 0; fi
    sleep 3
  done
  echo "'${title}' never published (pipeline failed or stalled)" >&2
  return 1
}

# The checks every ingest path must pass once its set is published.
assert_published_set() {
  local slug="$1"
  echo "published: ${slug}"

  echo "--- loudness measured (a -20 dBFS sine is ~-20 LUFS; -70 means a parse miss)"
  api GET "/api/sets/${slug}" \
    | json "d['normalized_lufs']" | { read -r lufs; echo "lufs: ${lufs}"; \
      python3 -c "import sys; v=float(sys.argv[1]); sys.exit(0 if -40 < v < 0 else 1)" "${lufs}"; }

  echo "--- stream is Opus"
  api GET "/api/sets/${slug}/stream" -o "${WORK}/stream"
  test "$(head -c 4 "${WORK}/stream")" = "OggS" || { echo "stream is not Ogg/Opus"; return 1; }
  echo "stream: $(wc -c <"${WORK}/stream" | tr -d ' ') bytes"

  echo "--- waveform peaks"
  api GET "/api/sets/${slug}/waveform" \
    | json "len(d['data'])" | { read -r n; test "${n}" -gt 0; echo "peaks: ${n}"; }
}
