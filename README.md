# Video understanding: own the pipeline, compare the cost

[![CI](https://github.com/pixeltable/showcase-video-orchestration-pipeline/actions/workflows/ci.yml/badge.svg)](https://github.com/pixeltable/showcase-video-orchestration-pipeline/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)

A runnable [Pixeltable](https://github.com/pixeltable/pixeltable) media pipeline and research paper comparing native video APIs with reusable evidence you prepare and control.

Your product can build an advantage through its data, evidence selection, and domain rules. This repository shows how to own those decisions in Python: keep media and intermediate results together, combine transforms with model calls, and reuse preparation across questions. The paper measures when that reuse lowers cost.

## Two ways to answer the same question

| Approach | What happens |
|---|---|
| Native API | Send the video and question to the model. Compare default and low-resolution input. |
| Pixeltable pipeline | Extract timestamped frames and audio, generate captions and a transcript, select evidence, then answer from it. Save preparation for later questions. |

**Built with:** Python, Pixeltable `TableModel`, typed `Video` / `Image` / `Audio`, iterator views, computed columns, Python UDFs, and SDK provider calls. Both benchmark approaches run in Pixeltable and use **Gemini 2.5 Flash**, with responses and usage stored for inspection. Additional paths use **fal**, **Amazon Nova / Bedrock**, and optional **local models**. **FastAPI** serves the local browser workspace.

## What the paper found

On **123 Video-MME questions from 41 videos**, three questions share each video's preparation:

<!-- results:readme-study:start -->

| Approach | Accuracy [95% CI] | List / question | Accounted / question |
| --- | ---: | ---: | ---: |
| 1 Native | 79.7% [70.7, 87.8] | $0.107 | $0.061 |
| 1L Native, low resolution | 83.7% [74.8, 91.1] | $0.055 | $0.040 |
| 2 Orchestrated (Pixeltable) | 79.7% [71.5, 87.0] | $0.029 | $0.028 |

<!-- results:readme-study:end -->

These are dated Gemini 2.5 / Pixeltable 0.7.11 results. Accounted costs estimate stored-response token usage including cache discounts; they are not invoices or total operating costs. Accuracy differences were unresolved on this sample. On the single interview clip, native low resolution was cheaper than orchestration. Read the [paper](docs/paper/paper.pdf) and [full results](docs/RESULTS.md) for the protocol and tradeoffs.

Current code targets **Pixeltable 0.7.16**. New agentic video has not been measured here; the [updated comparison protocol](docs/AGENTIC_VIDEO_COMPARISON.md) covers that next experiment.

## Try it

Requires Python 3.12+. Start with a real local graph without keys or model calls:

```bash
git clone https://github.com/pixeltable/showcase-video-orchestration-pipeline
cd showcase-video-orchestration-pipeline
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[workspace]"
run-evidence-workspace
```

Open the printed URL, then walk through the ownership lesson:

1. **Inspect the source.** Play the generated clip and examine its timestamped frames and extracted audio. Two requests share that preparation.
2. **Change the business rule.** Set minimum brightness to **128**. Existing request snapshots remain visible and become stale.
3. **Refresh one decision.** Refresh **first**: it uses two frames while **second** retains four. Source media and preparation stay unchanged.

![Local media workspace showing a rule change and one refreshed request](docs/images/evidence-workspace.jpg)

The workspace uses a temporary local catalog. Ctrl-C stops it; `run-media-demo` runs the terminal version.

## Make the pipeline yours

Change a policy and refresh one saved request:

```python
clips.update({'minimum_brightness': 128.0}, where=clips.clip_id == 'demo')
requests.recompute_columns('evidence', where=requests.request_id == 'first')
```

Start with [`local_graph.py`](src/video_benchmark/local_graph.py) and the [walkthrough](docs/WALKTHROUGH.md). Extend the [provider graph](src/video_benchmark/schema.py) with your sampling, selection, prompts, or domain UDFs; inspect saved evidence, responses, usage, and errors. [Run the provider comparisons](docs/RUNNING.md) with your own media and questions; cloud paths make paid calls. The motivation: [build an advantage through your multimodal data pipeline](https://www.pixeltable.com/blog/multimodal-ai-data-bottleneck).

[Workflow and extension points](docs/WORKFLOW.md) · [Deployment and recovery](docs/DEPLOYMENT.md) · [Validation](docs/REVIEW.md) · [More example apps](https://github.com/pierrebrunelle/awesome-pixeltable-apps)

Apache-2.0. Sample video: [Pixeltable docs](https://github.com/pixeltable/pixeltable/blob/main/docs/resources/The-Pursuit-of-Happiness.mp4). Video-MME annotations: academic use only.
