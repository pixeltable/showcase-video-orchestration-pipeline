# Blog draft: we were wrong about the cost of native video

> Status: draft for the Pixeltable blog. Companion to [the paper](../paper/paper.md). Numbers come from [docs/paper/numbers.json](../paper/numbers.json).

## Working title

**Native video or keyframes? Count every token before you choose.**

## Hook

Our own benchmark said that sampling keyframes and transcribing audio cost 66% less than sending Gemini the whole video. It was wrong. We had billed every token at one flat price, while Gemini bills video input at $0.30 per million tokens and output, including hidden thinking, at $2.50. Fixing the accounting turned a 66% saving into 18%, and a cheaper native setting beat both.

## The story in four beats

1. **The claim.** Orchestration (captions + transcript + one synthesis call) looked three times cheaper than native video on a four-minute clip.
2. **The audit.** Every call in the pipeline is a Pixeltable column, including each response's `usage_metadata`. Reading those columns showed video input priced 5x too high, output 40% too low, thinking tokens missing, and one synthesis per run billed twice.
3. **The fair rerun.** Same model, same question and instructions for every path, costs from reported tokens per modality, a native baseline at low media resolution, six runs per path, 123 Video-MME questions with paired tests.
4. **The result.** On one question about one clip, native at low resolution is cheapest ($0.0219) and orchestration ($0.0308) saves 18% over default native ($0.0376). On 123 Video-MME questions, three per video, native and orchestration had the same point accuracy (79.7%; low resolution 83.7%), with unresolved differences under video-level paired inference at a quarter of native's list price and half of low resolution's ($0.029, $0.107, and $0.055 per question).

## Why the numbers moved

Orchestration does not avoid tokens; it converts them. It swaps video input tokens, the cheapest kind, for generated captions and transcript, billed at the output rate. That trade pays off only when the generated evidence is reused: several questions about one video, or a video long enough that reading it once costs more than describing it.

## What readers should take away

- **Price from usage metadata, per modality.** Text length and flat rates are not cost.
- **Count thinking tokens.** On our native calls they were 37 to 66% of output-side tokens.
- **Compare against the cheap native setting.** `media_resolution=LOW` cut native video tokens by 73% with no loss on our clip.
- **Report list and response-accounted estimates together.** Gemini's implicit cache discounted one of six identical Pursuit runs by 70%, and served 49% of native input tokens when three Video-MME questions shared a video. After cache discounts, returned usage priced native at low resolution at 1.4 times orchestration instead of 1.9.
- **Expect refusals, and look for silent ones.** Gemini refused native calls on 2 of 41 videos, and withheld one transcript as recitation without raising an error. Orchestration lost a part; native lost the answer.

## How Pixeltable made the errors visible

- Each stage is a stored computed column: the caption, the transcript, the exact synthesis request, each response and its usage.
- The catalog is one declarative graph applied once; a synthesis table inserted after its run replaced a recompute sequence that had billed synthesis twice.
- Failed calls become per-cell errors; completed Video-MME batches are reused on resume. Interrupted and retried attempts may add spend not present in final-response totals.

## Try it

```bash
pip install -e .
run-media-demo                         # no keys, no API calls
# Set GOOGLE_API_KEY before the paid comparison:
run-benchmark --paths 1,1L,2
```

Open `results/<run_id>/REPORT.md` for the cost of every call.

## What not to say

- Do not say orchestration is cheaper in general; say when it is.
- Do not say the paths are equally accurate; 123 questions cannot resolve a gap under about ten points, and low resolution led on long videos.
- Label both prices as response-accounted estimates; list missing/retried attempts and compute/storage/egress exclusions.
- Do not present the local open-source path as measured; it was not run for this paper.
