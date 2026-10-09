#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ ! -d .venv ]]; then
  python3.12 -m venv .venv
fi

.venv/bin/pip install -q -U pip
.venv/bin/pip install -q -e ".[notebook]"
.venv/bin/python -m ipykernel install --user --name video-benchmark --display-name "video-benchmark"

exec .venv/bin/jupyter notebook notebooks/pipeline_analytics.ipynb
