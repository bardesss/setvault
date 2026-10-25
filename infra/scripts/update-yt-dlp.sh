#!/usr/bin/env bash
#
# update-yt-dlp.sh — bump the pinned yt-dlp version + run URL-rip tests.
#
# Cadence: run once a month, or immediately when a user reports a URL-rip
# regression. yt-dlp ships near-weekly with extractor fixes for shifting
# host page structures; staying pinned avoids surprise CI failures from
# upstream behavior changes, but we still need to track them.
#
# Usage:
#   infra/scripts/update-yt-dlp.sh                # bumps to latest, runs tests
#   infra/scripts/update-yt-dlp.sh 2026.05.01     # pins an explicit version
#
# Exit codes:
#   0  bump + tests succeeded (or already at latest)
#   1  failed to fetch latest version
#   2  url-rip tests failed at the new version (pin reverted)
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PYPROJECT="$ROOT/packages/core/pyproject.toml"

if [[ ! -f "$PYPROJECT" ]]; then
  echo "could not find $PYPROJECT" >&2
  exit 1
fi

current="$(grep -oE 'yt-dlp(\[[a-z,-]+\])?==[0-9]+\.[0-9]+\.[0-9]+' "$PYPROJECT" | head -1 | sed 's/.*==//')"
echo "current pin: ${current:-<none>}"

if [[ $# -ge 1 ]]; then
  target="$1"
else
  echo "fetching latest from PyPI..."
  target="$(curl -fsSL https://pypi.org/pypi/yt-dlp/json | python -c 'import json,sys; print(json.load(sys.stdin)["info"]["version"])')"
fi

if [[ -z "$target" ]]; then
  echo "could not resolve target version" >&2
  exit 1
fi

if [[ "$current" == "$target" ]]; then
  echo "already at $target — no change"
  exit 0
fi

echo "bumping $current -> $target"
# macOS/BSD sed differs from GNU sed; use a portable two-step.
python - "$PYPROJECT" "$current" "$target" <<'PY'
import sys, pathlib
path, old, new = sys.argv[1], sys.argv[2], sys.argv[3]
p = pathlib.Path(path)
text = p.read_text()
text = text.replace(f"yt-dlp[default]=={old}", f"yt-dlp[default]=={new}")
p.write_text(text)
PY

echo "syncing environment..."
(cd "$ROOT" && uv sync --reinstall-package yt-dlp >/dev/null)

echo "running url-rip test suite..."
if ! (cd "$ROOT" && uv run pytest apps/web/tests/test_url_rip*.py packages/core/tests/test_url_rip*.py -q); then
  echo "tests failed at $target — reverting pin" >&2
  python - "$PYPROJECT" "$target" "$current" <<'PY'
import sys, pathlib
path, old, new = sys.argv[1], sys.argv[2], sys.argv[3]
p = pathlib.Path(path)
text = p.read_text().replace(f"yt-dlp[default]=={old}", f"yt-dlp[default]=={new}")
p.write_text(text)
PY
  (cd "$ROOT" && uv sync --reinstall-package yt-dlp >/dev/null)
  exit 2
fi

echo "yt-dlp pinned at $target; commit the pyproject change."
