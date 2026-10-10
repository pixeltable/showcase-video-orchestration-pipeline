# Blog draft: we were wrong about the cost of native video

> Status: draft for the Pixeltable blog. Companion to [the paper](../paper/paper.md). Numbers come from [docs/paper/numbers.json](../paper/numbers.json).

> **Publication context, 2026-10-10:** this is an audit of recorded Gemini 2.5 experiments.
> Google's [agentic video announcement](https://blog.google/innovation-and-ai/models-and-research/gemini-models/introducing-agentic-video-in-gemini/)
> changes the baseline for a current comparison. Agentic mode has not been measured here.
> Publish these numbers as historical findings, with the [new comparison protocol](../AGENTIC_VIDEO_COMPARISON.md),
> rather than a claim about today's best architecture.

## Working title

**Native video or keyframes? Count every token before you choose.**

## Hook

Our own benchmark said that sampling keyframes and transcribing audio cost 66% less than sending Gemini the whole video. It was wrong. We had priced every token at one flat rate. At the recorded Gemini 2.5 Flash rates, video input cost $0.30 per million tokens and output, including thinking, cost $2.50. Fixing the accounting turned a 66% saving into 18% on our clip, and a lower-resolution native setting cost less than both.

## The story in four beats

1. **The claim.** Orchestration (captions + transcript + one synthesis call) looked three times cheaper than native video on a four-minute clip.
2. **The audit.** Every call in the pipeline is a Pixeltable column, including each response's `usage_metadata`. Reading those columns showed video input priced 5x too high, output 40% too low, thinking tokens missing, and one synthesis per run billed twice.
3. **The historical comparison.** Same Gemini 2.5 answer model, question, and guidance, with different media and perception settings; costs from reported tokens per modality; a low-resolution native setting; six clip runs per path; and 123 Video-MME questions with paired tests.
4. **The result.** On one question about one clip, native at low resolution is cheapest ($0.0219) and orchestration ($0.0308) saves 18% over default native ($0.0376). On 123 Video-MME questions, three per video, native and orchestration had the same point accuracy (79.7%; low resolution 83.7%), with unresolved differences under video-level paired inference at a quarter of native's list price and half of low resolution's ($0.029, $0.107, and $0.055 per question).

## Why the numbers moved

In these experiments, orchestration traded video input for generated captions and transcript at the output rate. Its economics improved when several questions reused that preparation. The result depends on the model, workload, cache behavior, and settings; it cannot predict what current agentic video processing will cost.

## What readers should take away

- **Price from usage metadata, per modality.** Text length and flat rates are not cost.
- **Count thinking tokens.** On our native calls they were 37 to 66% of output-side tokens.
- **Compare against current native options.** `media_resolution=LOW` cut tokens by 73% and retained our five phrase checks in the recorded clip experiment. A new study also needs a matched-model agentic arm; phrase checks do not establish unchanged semantic quality.
- **Report list and response-accounted estimates together.** Gemini's implicit cache discounted one of six identical Pursuit runs by 70%, and served 49% of native input tokens when three Video-MME questions shared a video. After cache discounts, returned usage priced native at low resolution at 1.4 times orchestration instead of 1.9.
- **Expect refusals, and look for silent ones.** Gemini refused native calls on 2 of 41 videos, and withheld one transcript as recitation without raising an error. Orchestration lost a part; native lost the answer.

## How Pixeltable made the errors visible

- Each stage is a stored computed column: the caption, the transcript, the exact synthesis request, each response and its usage.
- The catalog is one declarative graph applied once; a synthesis table inserted after its run replaced a recompute sequence that had billed synthesis twice.
- Failed calls become per-cell errors; completed Video-MME batches are reused on resume. Interrupted and retried attempts may add spend not present in final-response totals.

## What the newer provider capability changes

Adaptive inspection and provider-side context reuse make native video a stronger baseline.
Our next comparison keeps the model and API matched while testing static input, agentic
input, and application-owned evidence. We will measure independent questions and repeated
questions with retained state separately, giving native paths their available reuse options.

Pixeltable's demonstrated value remains concrete: keep source media and intermediate
results, inspect transformations and failures, query evidence across requests, and change
a business rule with deliberate refresh. A provider-managed answer service can fit inside
that application graph. Cost and quality claims need the new measurements.

## Try it

```bash
pip install -e .
run-media-demo                         # no keys, no API calls
# Set GOOGLE_API_KEY before the paid comparison:
run-benchmark --paths 1,1L,2 --preflight
# After checking inputs and deliberately choosing admission limits:
run-benchmark --paths 1,1L,2 --budget-usd 1 --max-attempts 64
```

Open `results/<run_id>/REPORT.md` for the cost of every call.
These commands run the implemented Gemini 2.5 paths; they do not run agentic mode.

## What not to say

- Do not say orchestration is cheaper in general; say when it is.
- Do not say the paths are equally accurate; 123 questions cannot resolve a gap under about ten points, and low resolution led on long videos.
- Label both prices as response-accounted estimates; list missing/retried attempts and compute/storage/egress exclusions.
- Do not present the local open-source path as measured; it was not run for this paper.
- Do not advertise a current cost or quality advantage over agentic Gemini before the
  matched-model experiment. Google's reported percentage gains are not ours to apply.
