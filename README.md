# Pixeltable Video Orchestration Benchmark

[![CI](https://github.com/pixeltable/showcase-video-orchestration-pipeline/actions/workflows/ci.yml/badge.svg)](https://github.com/pixeltable/showcase-video-orchestration-pipeline/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)

**Own the stack.** Native multimodal APIs process whole videos in one opaque call. Modular pipelines—keyframes, ASR, synthesis—let you **inspect, budget, and swap** every stage. This [Pixeltable](https://pixeltable.com) showcase runs both on the same clip and the same question so you can measure the tradeoff yourself.

| | Path 1 — Native Gemini | Path 2 — Orchestrated Gemini | Path 3 — Open source |
|--|------------------------|------------------------------|----------------------|
| Idea | Full video → one API call | Sparse frames + ASR → synth | Local VLM + WhisperX + 7B |
| Control | Low | High (frames, ASR, prompts) | Full (offline) |
| Typical cost (Pursuit ~255s) | ~$0.11 | ~$0.039 (~66% less) | $0 API |

Paths 1 and 2 use the **same** `gemini-2.5-flash` model—differences are architecture, not vendor marketing. Optional Path 4 (fal, 120s cap) and Path 5 (Nova / Bedrock) are provider baselines, not the hero story.

**Paper:** [docs/paper/paper.md](docs/paper/paper.md) · [PDF](docs/paper/paper.pdf)  
**Blog draft:** [docs/blog/DRAFT.md](docs/blog/DRAFT.md)  
**Golden export:** [results/golden/](results/golden/) (`fair_v1_nova_pro`)  
**Static side-by-side:** [docs/showcase.html](docs/showcase.html) (`python scripts/render_showcase.py`)  
**Lab notes:** [docs/LAB_RESULTS.md](docs/LAB_RESULTS.md)

---

## Quick start (Paths 1 + 2)

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[demo]"
cp .env.example .env          # set GOOGLE_API_KEY
python scripts/download_sample.py

run-benchmark --paths 1,2 --reset
```

Requires **Pixeltable 0.7.8** (`TableModel` class schemas). Use `--reset` when changing `--paths` or after a schema change so the catalog matches this package.

Read `results/<timestamp>/REPORT.md` for side-by-side answers and costs.

---

## Recipes

### 1. Native only — what the vendor default costs

```bash
run-benchmark --paths 1 --reset
```

### 2. Orchestrated — Pixeltable modular control

```bash
# optional: cp examples/orchestrated.env .env
run-benchmark --paths 2 --reset
```

Tune: `VISION_SAMPLE_KEYFRAMES`, `FRAME_SELECT_BUDGET`, `GEMINI_SYNTH_MAX_IMAGES` (see [examples/orchestrated.env](examples/orchestrated.env)).

### 3. Open source — take the stack offline

```bash
pip install -e ".[oss]"       # whisperx + expects llama-cpp-python
cp examples/oss.env .env      # HF_TOKEN for WhisperX diarization
run-benchmark --paths 3 --reset
```

### 4. Compare (default showcase)

```bash
run-benchmark --paths 1,2 --reset          # Gemini A/B
run-benchmark --paths 1,2,3 --reset        # + OSS when installed
```

---

## Showcase excerpt (golden run)

From [results/golden/summary.json](results/golden/summary.json) on the *Pursuit of Happyness* interview clip (~255s):

| Path | Cost |
|------|------|
| Native Gemini | **$0.114** |
| Orchestrated Gemini | **$0.039** |
| OSS | $0 |
| fal (120s cap) | $0.24 |
| Nova Pro | $0.060 |

Path 2 recovers the late unpaid-internship / “tonight” beats with inspectable keyframes + transcript—see [results/golden/REPORT.md](results/golden/REPORT.md).

---

## Optional: Video-MME (quantitative)

Stratified 30-Q MCQ eval (Gemini 1–2, OSS, Nova; fal omitted):

```bash
pip install -e ".[videomme]"
run-videomme-dev --paths 1,2
```

Reference: `results/videomme-dev/20260711T025812Z` (Gemini, ASR-fixed). Four-path notes: `…/20260711T052512Z/COMPARISON.md`. Contaminated early run `…T012446Z` is invalid—ignore it.

---

## Customize (intentional knobs)

| Knob | Default | Effect |
|------|---------|--------|
| `VISION_SAMPLE_KEYFRAMES` | 24 | Even samples across the timeline |
| `FRAME_SELECT_BUDGET` | 16 | Keep frames near scene cuts |
| `GEMINI_SYNTH_MAX_IMAGES` | 8 | Images re-attached at Path 2 synth |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Paths 1–2 |
| `OSS_*` / `OSS_ASR` | see examples | Path 3 models / ASR |
| Prompts | `udfs.py`, `videomme/prompts.py` | Frame + synthesis wording |

Full env reference: [docs/WORKFLOW.md](docs/WORKFLOW.md). Architecture diagrams live there too.

---

## Inspect catalog

```bash
./scripts/notebook.sh    # video-benchmark kernel
```

Power-user only—CLI is the front door.

---

## Project layout

```
src/video_benchmark/     # Pursuit catalog + CLI (schema.py = TableModel)
  videomme/              # optional Video-MME eval (schema.py = TableModel)
docs/paper/              # research write-up + PDF
docs/blog/               # narrative draft
docs/showcase.html       # static path comparison
examples/                # recipe .env files
results/golden/          # committed headline export
```

---

## Development

```bash
pip install -e ".[dev,demo]"
pytest
ruff check src tests
```

Tune A/B sweeps (`scripts/run_tune_ab.sh`) are **lab tooling**—not required for the showcase.

## License

Apache-2.0. Sample video from [Pixeltable docs](https://github.com/pixeltable/pixeltable/blob/main/docs/resources/The-Pursuit-of-Happiness.mp4). Video-MME annotations: academic use only.
