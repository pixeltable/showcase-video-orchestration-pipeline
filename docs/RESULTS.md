# Recorded video comparisons

These experiments used Pixeltable 0.7.11 and Gemini 2.5. They do not measure current agentic mode. Use the [updated comparison protocol](AGENTIC_VIDEO_COMPARISON.md) for a new study. The application currently targets Pixeltable 0.7.16.

On a 255-second interview clip (mean of six runs, list price, `gemini-2.5-flash` rates of 2026-09-28):

<!-- results:results-clip:start -->

| Path | List price per answer | Clip phrase checks |
| --- | ---: | ---: |
| 1 Native | $0.0376 | 5/5 |
| 1L Native, low resolution | $0.0219 | 5/5 |
| 2 Orchestrated | $0.0308 | 5/5 |
| 4 fal video-understanding | $0.2400 | 2/5 |
| 5 Amazon Nova Pro | $0.0600 | 1/5 |

<!-- results:results-clip:end -->

On 123 Video-MME questions (41 videos, 12.2 hours, three questions per video):

<!-- results:results-videomme:start -->

| Path | Accuracy [95% CI] | List price per question | Response-accounted per question |
| --- | ---: | ---: | ---: |
| 1 Native | 79.7% [70.7, 87.8] | $0.107 | $0.061 |
| 1L Native, low resolution | 83.7% [74.8, 91.1] | $0.055 | $0.040 |
| 2 Orchestrated | 79.7% [71.5, 87.0] | $0.029 | $0.028 |
| 5 Amazon Nova Lite | 58.5% [50.4, 66.7] | $0.010 | $0.010 |

<!-- results:results-videomme:end -->

Intervals resample whole videos; paired video-level tests do not resolve the Gemini differences on this sample (p >= 0.27). That does not establish equivalent accuracy. The sample comprises locally available Video-MME videos, and the five clip checks above are phrase heuristics, not a general quality score. Gemini refused both native settings on 2 of the 41 videos; the orchestrated path returned an answer for every question. Exports: [results/paper/](../results/paper/).

“Billed” in historical exports means **response-accounted cost estimated from token usage after cache discounts**, not a reconciled invoice. Retried or interrupted calls without stored usage, provider refusals, local compute, storage, and egress can add unrecorded spend. Prices are a dated snapshot; see [cost boundaries](../docs/WORKFLOW.md#cost-accounting).

In this recorded Gemini 2.5 experiment, orchestration traded video input ($0.30 per million tokens) for generated captions and transcript ($2.50 per million output tokens). Reusing preparation across three questions improved its measured economics; Gemini's implicit cache also discounted native input. These dated results do not predict the cost or quality of current agentic processing.

> **Correction.** An earlier version of this repository reported that orchestration cost 66% less than native ($0.039 vs $0.114). That figure came from a flat $1.50 per million token price, which overcharged video input fivefold, and from uncounted thinking tokens. Section 3 of the paper lists every correction.
