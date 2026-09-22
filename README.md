# Pixeltable showcase: video orchestration pipeline

[![CI](https://github.com/pixeltable/showcase-video-orchestration-pipeline/actions/workflows/ci.yml/badge.svg)](https://github.com/pixeltable/showcase-video-orchestration-pipeline/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)

Five-path **CLI** (`run-benchmark` / `run-videomme-dev`) on Pixeltable **0.7.8 `TableModel` + `update_all()`**. Catalogs: `video_benchmarking/` (Pursuit) and `videomme/`. This is a batch benchmark, not a FastAPI / `pxt service` app.

Native multimodal APIs process a whole video in one opaque call. Modular pipelines—keyframes, ASR, synthesis—let you **inspect, budget, and swap** every stage. Same clip, same question.

| | Path 1 Native Gemini | Path 2 Orchestrated Gemini | Path 3 Open source | Path 4 fal | Path 5 Nova |
|--|----------------------|----------------------------|--------------------|------------|-------------|
| Idea | Full video → one API call | Sparse frames + ASR → multimodal synth | Local VLM + WhisperX + 7B | `fal-ai/video-understanding` | Bedrock `converse` |
| Control | Low | High | Full (offline) | Low (120s cap) | Low |
| Typical cost (Pursuit ~255s) | ~$0.11 | ~$0.039 (~66% less) | $0 API | $0.24 | $0.060 |

Paths 1 and 2 use the **same** `gemini-2.5-flash` model. Paths 4–5 are optional provider baselines.

**Paper:** [docs/paper/paper.md](docs/paper/paper.md) (PDF: `./scripts/build_paper.sh`)  
**Blog draft:** [docs/blog/DRAFT.md](docs/blog/DRAFT.md)  
**Golden export:** [results/golden/](results/golden/) (`fair_v1_nova_pro`)  
**Static side-by-side:** [docs/showcase.html](docs/showcase.html)  
**Lab notes:** [docs/LAB_RESULTS.md](docs/LAB_RESULTS.md)

---

## Quick start (Paths 1 + 2)

```bash
git clone https://github.com/pixeltable/showcase-video-orchestration-pipeline
cd showcase-video-orchestration-pipeline
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[demo]"   # alias for the base Gemini install
cp .env.example .env       # set GOOGLE_API_KEY
python scripts/download_sample.py

run-benchmark --paths 1,2 --reset
```

Use **`--reset`** whenever you change `--paths` or the schema. Path-gated `TableModel` columns are not migrated in place.

Read `results/<timestamp>/REPORT.md`. Path 1-only exports skip `keyframes.csv`.

---

## Other recipes

**Native only**

```bash
run-benchmark --paths 1 --reset
```

**Orchestrated only** — optional: `cp examples/orchestrated.env .env`

```bash
run-benchmark --paths 2 --reset
```

**Open source**

```bash
pip install -e ".[oss]"       # whisperx; install llama-cpp-python separately
cp examples/oss.env .env      # HF_TOKEN for WhisperX diarization
run-benchmark --paths 3 --reset
```

**Gemini A/B + OSS**

```bash
run-benchmark --paths 1,2,3 --reset
```

**Optional Path 4 / Path 5**

```bash
pip install -e ".[fal]"       # ENABLE_FAL=1 and FAL_KEY
run-benchmark --paths 4 --reset

pip install -e ".[bedrock]"   # ENABLE_NOVA=1 and AWS/Bedrock creds
run-benchmark --paths 5 --reset   # Pursuit default: Nova Pro
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

Path 2 recovers the late unpaid-internship / “tonight” beats — [results/golden/REPORT.md](results/golden/REPORT.md).

---

## Optional: Video-MME (quantitative)

Stratified 30-Q MCQ eval. Default paths are **1,2** (same as Pursuit). Path 3 uses **shared Gemini ASR** (paid) plus local VLM captions (not WhisperX). Wrapper / unset `NOVA_MODEL_ID` prefers Nova **Lite**; Pursuit Path 5 defaults to **Pro**. Video-MME raises sample/select to **32 / 24** even when `.env` sets the Pursuit 24/16 knobs. Override with `VIDEOME_VISION_SAMPLE_KEYFRAMES` and `VIDEOME_FRAME_SELECT_BUDGET`. Architecture: [docs/WORKFLOW.md](docs/WORKFLOW.md).

```bash
pip install -e ".[videomme]"
run-videomme-dev --paths 1,2 --reset
```

Exports land in local `results/videomme-dev/` (gitignored). Numbers: [docs/LAB_RESULTS.md](docs/LAB_RESULTS.md) and [docs/paper/paper.md](docs/paper/paper.md).

---

## Customize (intentional knobs)

| Knob | Default | Effect |
|------|---------|--------|
| `VISION_SAMPLE_KEYFRAMES` | 24 | Even samples (`num_frames`); unused when scene-aware is off and `MAX_VISION_KEYFRAMES` is set |
| `FRAME_SELECT_BUDGET` | 16 | Keep frames near scene cuts |
| `GEMINI_SYNTH_MAX_IMAGES` | 8 | Images re-attached at Path 2 synth |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Paths 1–2 |
| `OSS_*` / `OSS_ASR` | see examples | Path 3 models / ASR |
| Prompts | `udfs.py`, `videomme/prompts.py` | Frame + synthesis wording |

Inspect the catalog with `pxt ls` / `pxt rows`. Operator detail: [docs/WORKFLOW.md](docs/WORKFLOW.md). The notebook is power-user only and assumes a modular catalog.

---

## Project layout

```
src/video_benchmark/     # Pursuit catalog + CLI (schema.py = TableModel)
  videomme/              # optional Video-MME eval
docs/paper/              # research write-up
docs/showcase.html       # static Path 1–3 cards; 4–5 live in golden REPORT
examples/                # recipe .env files
results/golden/          # committed headline export
```

---

## Development

```bash
pip install -e ".[dev,demo]"
pytest
ruff check src tests scripts
```

Tune A/B sweeps (`scripts/run_tune_ab.sh`) are lab tooling.

## License

Apache-2.0. Sample video from [Pixeltable docs](https://github.com/pixeltable/pixeltable/blob/main/docs/resources/The-Pursuit-of-Happiness.mp4). Video-MME annotations: academic use only.
