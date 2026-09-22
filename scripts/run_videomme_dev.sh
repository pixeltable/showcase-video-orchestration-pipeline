#!/usr/bin/env bash
# Video-MME dev slice: stratified 30 Q. Default paths are 1,2.
# Opt in with --paths 1,2,3,5. Pass --reset after a path or schema change.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -f .venv/bin/activate ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

export VIDEOME_DEV_N="${VIDEOME_DEV_N:-30}"
export VIDEOME_DEV_SEED="${VIDEOME_DEV_SEED:-42}"
export NOVA_MODEL_ID="${NOVA_MODEL_ID:-amazon.nova-lite-v1:0}"

exec run-videomme-dev "$@"
