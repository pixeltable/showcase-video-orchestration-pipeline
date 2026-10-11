# Own your video pipeline with Pixeltable

[![CI](https://github.com/pixeltable/showcase-video-orchestration-pipeline/actions/workflows/ci.yml/badge.svg)](https://github.com/pixeltable/showcase-video-orchestration-pipeline/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)

Keep videos, frames, audio, and model responses in one [Pixeltable](https://github.com/pixeltable/pixeltable) catalog. Declare transformations and API calls in Python, query saved evidence, and choose when decisions refresh.

- Work with typed `Video`, `Image`, and `Audio` columns.
- Prepare evidence once and reuse it across requests.
- Inspect intermediate results and failures alongside the source.
- Keep provider choices and business rules in your application.

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

The workspace binds to loopback and uses a temporary catalog. Ctrl-C stops it. Run `run-media-demo` for the terminal version.

## Change the pipeline

The policy and refresh are ordinary SDK operations:

```python
clips.update({'minimum_brightness': 128.0}, where=clips.clip_id == 'demo')
requests.recompute_columns('evidence', where=requests.request_id == 'first')
```

Start with [`local_graph.py`](src/video_benchmark/local_graph.py) and the [walkthrough](docs/WALKTHROUGH.md). The [provider graph](src/video_benchmark/schema.py) extends the pattern with captions, transcription, synthesis, and stored usage. [Run provider comparisons](docs/RUNNING.md) when you need them; cloud paths make paid calls.

## Explore the research

The [recorded results](docs/RESULTS.md) compare native video with saved-evidence pipelines on Gemini 2.5. They used Pixeltable **0.7.11**; the current application targets **0.7.16**. Agentic video has not been measured here: see the [updated comparison protocol](docs/AGENTIC_VIDEO_COMPARISON.md).

[Workflow and extension points](docs/WORKFLOW.md) · [Paper](docs/paper/paper.md) · [Deployment and recovery](docs/DEPLOYMENT.md) · [Validation](docs/REVIEW.md)

Apache-2.0. Sample video: [Pixeltable docs](https://github.com/pixeltable/pixeltable/blob/main/docs/resources/The-Pursuit-of-Happiness.mp4). Video-MME annotations: academic use only.
