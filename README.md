# Own your video pipeline with Pixeltable

[![CI](https://github.com/pixeltable/showcase-video-orchestration-pipeline/actions/workflows/ci.yml/badge.svg)](https://github.com/pixeltable/showcase-video-orchestration-pipeline/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)

Own your media, business rules, and orchestration in Python. [Pixeltable](https://github.com/pixeltable/pixeltable) keeps videos, frames, audio, and model responses in one queryable catalog; computed columns connect transformations, Python UDFs, and API calls.

## What you'll learn

- Use typed `Video`, `Image`, and `Audio` in the same graph.
- Prepare frames and audio once, then reuse them across requests.
- Change a rule and refresh one decision without repeating preparation.
- Inspect stored evidence, model responses, and failures.

## Try it

Requires Python 3.12+. This workspace runs a real local Pixeltable graph without keys or model calls.

```bash
git clone https://github.com/pixeltable/showcase-video-orchestration-pipeline
cd showcase-video-orchestration-pipeline
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[workspace]"
run-evidence-workspace
```

Open the printed URL. Play the generated clip and inspect its frames and audio. Set minimum brightness to **128**, then refresh **first**: it uses two frames while **second** retains four. Preparation stays unchanged.

![Local media workspace showing a rule change and one refreshed request](docs/images/evidence-workspace.jpg)

The workspace uses a temporary local catalog. Ctrl-C stops it; `run-media-demo` runs the terminal version.

## Change the pipeline

Change a policy and refresh one saved request:

```python
clips.update({'minimum_brightness': 128.0}, where=clips.clip_id == 'demo')
requests.recompute_columns('evidence', where=requests.request_id == 'first')
```

Start with [`local_graph.py`](src/video_benchmark/local_graph.py) and the [walkthrough](docs/WALKTHROUGH.md). The [provider graph](src/video_benchmark/schema.py) adds captions, transcription, synthesis, and stored usage. [Provider comparisons](docs/RUNNING.md) make paid calls.

## Explore the research

The [recorded results](docs/RESULTS.md) compare native video with saved-evidence pipelines on Gemini 2.5. They used Pixeltable **0.7.11**; the current application targets **0.7.16**. Agentic video has not been measured here: see the [updated comparison protocol](docs/AGENTIC_VIDEO_COMPARISON.md).

[Workflow and extension points](docs/WORKFLOW.md) · [Paper](docs/paper/paper.md) · [Deployment and recovery](docs/DEPLOYMENT.md) · [Validation](docs/REVIEW.md) · [More example apps](https://github.com/pierrebrunelle/awesome-pixeltable-apps)

Apache-2.0. Sample video: [Pixeltable docs](https://github.com/pixeltable/pixeltable/blob/main/docs/resources/The-Pursuit-of-Happiness.mp4). Video-MME annotations: academic use only.
