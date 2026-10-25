#!/usr/bin/env bash
# Smoke for yt-dlp's YouTube helpers: Deno is on PATH for yt-dlp-ejs (the
# JS-challenge solver), and the bgutil PO-token server answers /ping on
# 127.0.0.1:4416, where the bgutil-ytdlp-pot-provider plugin looks for it.
# Offline: minting a token needs YouTube, so only liveness is checked.
#
# Usage: CONTAINER=sv infra/docker/test/smoke_pot_provider.sh
set -euo pipefail

CONTAINER="${CONTAINER:?CONTAINER unset}"
DEADLINE="${POT_TIMEOUT:-60}"

echo "--- deno + yt-dlp-ejs + PO-token plugin"
docker exec "${CONTAINER}" deno --version
docker exec "${CONTAINER}" python -c \
  "import yt_dlp, yt_dlp_ejs, yt_dlp_plugins.extractor.getpot_bgutil_http; print('yt-dlp', yt_dlp.version.__version__)"

echo "--- waiting up to ${DEADLINE}s for the PO-token server"
for _ in $(seq 1 $((DEADLINE / 2))); do
  if PING="$(docker exec "${CONTAINER}" curl -fsS http://127.0.0.1:4416/ping 2>/dev/null)"; then
    echo "ping: ${PING}"
    echo "pot-provider smoke OK"
    exit 0
  fi
  sleep 2
done
echo "the PO-token server never answered on 127.0.0.1:4416"
docker exec "${CONTAINER}" sh -c 's6-svstat /run/service/pot-provider 2>/dev/null' || true
docker logs "${CONTAINER}" 2>&1 | tail -n 40
exit 1
