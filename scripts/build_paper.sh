#!/usr/bin/env bash
# Build docs/paper/paper.pdf from paper.md + references.bib + figures/.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if ! command -v pandoc >/dev/null 2>&1; then
  echo "error: pandoc not found. Install with: brew install pandoc" >&2
  exit 1
fi
if ! command -v tectonic >/dev/null 2>&1; then
  echo "error: tectonic not found. Install with: brew install tectonic" >&2
  exit 1
fi

mkdir -p docs/paper/figures
if [[ ! -f docs/paper/figures/cost_by_path.png ]]; then
  echo "Generating figures..."
  python scripts/build_paper_figures.py
fi

pandoc docs/paper/paper.md \
  --citeproc \
  --bibliography docs/paper/references.bib \
  --pdf-engine=tectonic \
  -V geometry:margin=1in \
  -V fontsize=11pt \
  --toc \
  --resource-path=docs/paper \
  -o docs/paper/paper.pdf

echo "Wrote docs/paper/paper.pdf ($(wc -c < docs/paper/paper.pdf | tr -d ' ') bytes)"
