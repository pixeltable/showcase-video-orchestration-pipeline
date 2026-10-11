# Run provider comparisons

Start with the [local workspace](../README.md#try-it) to inspect the graph without provider calls. The commands below extend that installation with paid or local-model paths.

## Run an optional provider comparison (Paths 1, 1L, 2)

```bash
cp .env.example .env       # set GOOGLE_API_KEY
run-benchmark --paths 1,1L,2 --preflight
run-benchmark --paths 1,1L,2 --budget-usd 1 --max-attempts 64
```

After the base installation above, this downloads the sample clip, builds the `video_benchmarking` catalog, and writes `results/<run_id>/`: `REPORT.md`, `summary.json` (answers, usage, and response-accounted cost), `keyframes.csv`, and `manifest.json` (config, prices, versions, source and media identities). The recorded default comparison was about $0.09 at the documented rates; new runs make paid API calls and their cost can vary.

Managed CLI runs reserve estimated cost **before every supported model send**, including retries and calls triggered during schema application. The default shared ledger is `results/provider-ledger.sqlite3`; pending or unknown attempts retain their reservations across restarts. Budget defaults to **$1**, attempts to **64 per invocation**, and media duration to **600 seconds**. Gemini and Nova output is capped at **4,096 tokens**, a changed experimental definition for future runs. Downloads and polling are not model attempts. Preflight may download media and checks configured credentials, not provider access; it makes no model calls or catalog changes.

The budget bounds admission using dated prices and conservative envelopes; it is **not an invoice ceiling**. An unknown attempt can coexist with more work while its held reservation fits the remaining budget. Fal records queue acceptance and a duration estimate; final polled output remains in the catalog. Unsupported model endpoints fail before send. Direct SDK calls outside these managed CLIs do not inherit the guard. Inspect the [attempt contract](../docs/WALKTHROUGH.md#admit-paid-work-deliberately) before changing limits or recovering a run.

## Optional provider paths

| Path | Mechanism | Install |
|------|-----------|---------|
| `1` | `gemini.generate_content` on the video and the question | base |
| `1L` | Path 1 with `media_resolution=LOW` | base |
| `2` | Gemini caption per keyframe, Gemini transcript, scene-aware frame selection, one multimodal synthesis call | base |
| `3` | The same keyframes captioned by Qwen2.5-VL-3B, WhisperX transcript, Qwen2.5-7B synthesis, all local | `.[oss]` + `llama-cpp-python` |
| `4` | `fal.run` on `fal-ai/video-understanding` (first 120 s) | `.[fal]`, `FAL_KEY` |
| `5` | `bedrock.converse` with Amazon Nova; video that is not H.264 or exceeds the inline limit is re-encoded to the frames Nova samples | `.[bedrock]`, AWS credentials, `ffmpeg` |

```bash
run-benchmark --paths 1,2 --video my_clip.mp4 --query "What happens after the meeting?"
run-benchmark --paths 1,1L,2 --repeats 5          # five independent runs
run-benchmark --paths 3 --reset                   # a catalog is built for one path set
```

A benchmark catalog freezes paths, effective configuration, computation-source digest, and SDK version. Select paths with `--paths`; unused environment settings do not gate a run. Changing the frozen definition asks for `--reset`, which drops that benchmark catalog but keeps `results/`. Export runs before resetting. This is an experiment isolation policy; applications can instead use Pixeltable schema migration and selective recomputation.

## Video-MME

```bash
pip install -e ".[videomme]"
run-videomme --n 30 --paths 1,1L,2 --preflight  # sample/download; no model calls
run-videomme --local-only --n 123 --paths 1,1L,2,5 --preflight
```

The small default admission limits can reject or stop a full research run. Inspect the sample manifest and duration first, then supply a deliberately chosen budget, attempt limit, and media-duration limit. A paired rerun must preserve exact question/media identities and effective settings; the same count and seed are insufficient. [Research contribution checks](../docs/WALKTHROUGH.md#make-a-research-change-reviewable) define the required evidence.

Questions share their video's captions and transcript, so orchestration prepares evidence once per video. `run-videomme` checks all proposed input identities before inserting any rows: an existing ID with changed media bytes, annotation revision, question, options, or answer is rejected. Identical inputs resume without new calls; adding a question to the same video runs only its answer stage. Interrupted calls that did not commit can be repeated. Persisted failures need explicit recomputation; see [failure recovery](../docs/WORKFLOW.md#failures-and-changes). Exports include clustered accuracy and difference intervals, paired video-level tests, costs, predictions, and identities saved when inputs were accepted. Annotation revision is pinned in [`sample.py`](../src/video_benchmark/videomme/sample.py).

## Benchmark settings

| Variable | Default | Effect |
|----------|---------|--------|
| `GEMINI_MODEL` | `gemini-2.5-flash` | Model for Paths 1, 1L, 2; must have a price in [`pricing.py`](../src/video_benchmark/pricing.py) |
| `VISION_SAMPLE_KEYFRAMES` | 24 | Frames sampled evenly for captions |
| `FRAME_SELECT_BUDGET` | 16 | Frames kept for synthesis, nearest to scene cuts and spread over the timeline |
| `GEMINI_SYNTH_MAX_IMAGES` | 8 | Kept frames attached as images to the synthesis call |
| `OSS_ASR` | `whisperx` | Path 3 transcript: `whisperx` (needs `HF_TOKEN`), `whisper`, or `gemini` |
| `NOVA_MODEL_ID` | `amazon.nova-pro-v1:0` | Path 5 model (Video-MME defaults to Nova Lite) |

Prompts live in [`prompts.py`](../src/video_benchmark/prompts.py) and [`videomme/prompts.py`](../src/video_benchmark/videomme/prompts.py); every path that writes an answer shares the same question and guidance.

## Inspect a run

```bash
pxt ls video_benchmarking
pxt rows video_benchmarking/keyframes -n 5 --cols position_sec,gemini_caption,gemini_caption_cost
pxt rows video_benchmarking/syntheses -n 1 --cols gemini_prompt,gemini_answer,gemini_total_cost
```

[`notebooks/pipeline_analytics.ipynb`](../notebooks/pipeline_analytics.ipynb) walks one run through every stage (`./scripts/notebook.sh`). Run it while no benchmark is running: a new Pixeltable process clears the catalog's temporary files.

## Development
```bash
pip install -e ".[dev,workspace,fal]"
pytest                       # offline: a fake Gemini client and a generated test video
ruff check src tests scripts
python scripts/schema_apply_smoke.py
python -m video_benchmark.local_demo
python -m video_benchmark.quality
```

The Pixeltable release is the `pixeltable==` pin in [`pyproject.toml`](../pyproject.toml). [CI](../.github/workflows/ci.yml) checks the pin, lint, offline provider tests, CLI help, repeated isolated schema application, a real local media graph, and showcase rendering. [Upgrade watch](../.github/workflows/upgrade-watch.yml) tests newer releases with their dependencies and fails with a pin-bump notice when they pass. [Dependabot](../.github/dependabot.yml) updates GitHub Actions.

To rebuild the paper: install `.[paper]`, then run `python scripts/build_paper_figures.py`, `python scripts/render_paper_tables.py`, and `./scripts/build_paper.sh` (needs `pandoc` and `tectonic`). The README comparison, [results](RESULTS.md), and paper tables come from `docs/paper/numbers.json`; `python scripts/render_paper_tables.py --check` detects drift without writing. Keep the README focused on the comparison and walkthrough, with detailed measurements in the results and paper. Reanalysis reads the committed exports and makes no provider calls.
