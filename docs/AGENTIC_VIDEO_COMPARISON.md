# Video comparison after Gemini's agentic update

Reviewed **2026-10-10**. This is a capability review and proposed experiment, not a new
benchmark result. The implemented paid paths still use `generateContent` and the known
Gemini 2.5 price entries. Interactions model requests are deliberately rejected inside
the managed admission context until their accounting and lifecycle are supported.

## What changed

Google's September 1 [announcement](https://blog.google/innovation-and-ai/models-and-research/gemini-models/introducing-agentic-video-in-gemini/)
describes provider-managed selection of video segments and modalities. Its “up to”
66% cost reduction, 88% token reduction, and 7% quality improvement are Google's results;
they are not measurements on this repository's media or queries.

The announcement names Gemini 3.7 Flash. The [current model guide](https://ai.google.dev/gemini-api/docs/latest-model)
instead identifies `gemini-3.8-flash` as the latest Flash model. The
[video guide](https://ai.google.dev/gemini-api/docs/video-understanding) documents both
static and agentic modes for it: static defaults to 1 FPS; agentic adjusts inspection
based on the question. Google recommends considering static for short, latency-sensitive
clips. Agentic uses Interactions with `processing: agentic` on the video input, rather
than a flag on our current Pixeltable `generate_content` expression.

Google also provides observable execution steps and optional conversation state through
`previous_interaction_id`. Its [Interactions overview](https://ai.google.dev/gemini-api/docs/interactions-overview)
describes state-assisted caching. Native reuse and inspectability belong in the comparison;
they are not exclusive Pixeltable advantages.

Our recorded Gemini 2.5 results remain evidence about those models, prompts, prices, and
inputs. They do not establish superiority over this newer capability. Preserve the paper,
predictions, figures, and raw exports; do not subtract a vendor percentage from their costs.

## The product question

A developer needs to know which approach meets a task's quality, latency, cost, and data
requirements. A researcher needs a comparison that separates a better model from a
different processing mode. A universal “orchestration wins” claim serves neither audience.

| Need | Provider capability to acknowledge | Pixeltable lesson demonstrated here |
|---|---|---|
| Inspect a video for a question | Static native input; adaptive agentic inspection | Keep typed source media and derived results together |
| Ask further questions | Provider cache and optional conversation state | Query shared preparation from independent request rows |
| Inspect an answer's basis | Provider execution steps | Store frame/audio outputs, captions, transcript, responses, and selection rules |
| Change an application policy | Prompt or provider configuration changes | Update a rule, retain old request evidence, deliberately refresh one decision |
| Use other processing services | Each provider's supported interfaces | Combine ordinary SDK expressions with application-owned transformations |

The local workspace proves preparation reuse and scoped refresh without a model. The
provider benchmark records intermediate model outputs, including errors and hallucinations.
These are useful application properties even if agentic Gemini is the best answer service.
A future agentic call can itself be a computed column with stored response and usage;
Pixeltable and provider-managed inspection can be used together. That integration is proposed,
not implemented or measured here.

## The next experiment

Use one verified current model and the same Interactions API for all proposed arms.
These labels are experiment names, not supported `--paths` values:

| Arm | Input and processing | What its comparison isolates |
|---|---|---|
| S: static native | Original video; explicitly `processing: static` | Current-model baseline |
| A: agentic native | Same bytes and question; explicitly `processing: agentic` | A versus S measures processing-mode effects |
| P: stored evidence | Query-agnostic captions and transcript, selected frames, then synthesis | P versus A compares application-owned preparation with provider-managed inspection |

Use the current model for P's perception and answer calls too. Report any configuration
differences, including perception thinking, media resolution, answer limits, and API features.
Matched model names alone do not isolate architecture. Retain the historical low-resolution
arm as historical context; validate an equivalent current low-cost setting before adding it.

Start with three fixed fixtures: a short clip, a long video with a localized answer, and a
case requiring audio or a rapid visual change. Independently label answer evidence and
timestamps before looking at outputs. This pilot validates mode serialization, response
accounting, lifecycle, and evaluator suitability. It cannot support an accuracy headline.

Then run the exact recorded 41-video/123-question identities in a new catalog and export
directory. Keep all attempted questions, including refusals and failures. Save bytes hashes,
annotation revision, prompts, effective configuration, model/version identifiers, SDK
versions, request/interaction identities, and complete attempt receipts. Do not recreate
the cohort merely by reusing the count and seed.

Measure two workloads separately:

- **Independent questions:** one question and three questions per video, with no previous
  interaction history. Apply the same policy for optional explicit caching to both native
  arms; record observed implicit cache use. Charge preparation and uploads consistently.
- **Repeated questions with retained state:** give native arms their own conversation chains
  and P its shared evidence. Use identical question order, record context/state and cache
  costs, and report the order and any carryover effect. Ground-truth answers never enter
  model context. Additional ten-question workloads need new labelled inputs and separate
  reporting rather than being merged into the historical cohort.

Report accuracy and evidence correctness, end-to-end completion time including upload and
polling, complete versus unknown costs, and the cost of the first and subsequent questions.
Use paired video-level inference for the cohort; unresolved differences do not establish
equivalence. A model-generated timestamp or processing trace is evidence to check, not ground
truth. Avoid selecting a different winning arm after seeing each test answer.

## Accounting and implementation gates

The [pricing snapshot](https://ai.google.dev/gemini-api/docs/pricing) checked on October 10
lists these Gemini 3.8 Flash **standard Developer API** rates per million tokens:

| Rate | Through 2026-12-31 | From 2027-01-01 |
|---|---:|---:|
| Input | $0.75 | $1.50 |
| Output, including thinking | $3.75 | $7.50 |
| Cached input | $0.075 | $0.15 |
| Explicit cache storage, per hour | $0.50 | $1.00 |

Record service tier, rate date, and cache/storage policy with each run. These rates do not
replace the historical Gemini 2.5 snapshot. Report any post-run repricing separately.

The [Interactions reference](https://ai.google.dev/api/interactions-api) uses fields such as
`total_input_tokens`, `total_output_tokens`, `total_thought_tokens`, and `total_tool_use_tokens`.
Our current `usageMetadata` parser is not an Interactions parser. Verify how all reported
categories are billed and overlap before summing them. Preserve raw usage and execution
steps; absent or inconsistent usage remains unknown cost.

Before enabling A or S in a managed run:

1. Verify the selected account's model and video-mode access. Test that the requested mode
   reaches the wire without silent fallback. The former installed `google-genai` 2.10.0
   dropped `processing`; 2.29.0 preserves it in offline real-SDK serialization tests. The
   dependency minimum is now 2.29.0. Serialization does not prove server-side execution.
2. Extend admission for actual Interactions creation sends and SDK retries. Do not reuse
   the static video token-per-second envelope as an agentic upper bound. Define a justified
   reservation policy for internal passes and thinking; an output cap alone cannot provide
   a provider invoice ceiling. Unsupported endpoints remain blocked until tested.
3. Persist the provider interaction ID as soon as accepted. Resume a background task by
   polling its ID, rather than resubmitting on timeout. Keep unresolved spending reserved;
   reconcile terminal usage once per ID. Verify completion, refusal, cancellation, missing
   usage, interruption, retries, and restoration with offline fixtures before a paid pilot.
4. Implement the smallest public-SDK adapter required by Pixeltable's available built-ins.
   Keep full interaction state, response, usage, and answer separate. Start a new definition
   digest and catalog; never relabel a static result as agentic.

## Decision and next access needed

Three viable actions were considered: update claims and protocol now; enable a guarded
three-fixture pilot after implementing the gates; or immediately replace the published
benchmark. We choose the first, followed by the pilot. Immediate replacement would mix
model, API, workload, and accounting changes before validating any of them.

Success for this update is that readers can distinguish recorded evidence, documented
capabilities, and proposed work, and that unaccounted Interactions requests cannot escape
the managed guard. A pilot falsifies the proposed path if the mode is ignored, usage cannot
be reconciled, or the evaluator fails to distinguish truthful from fabricated evidence.
Any quality or cost preference must follow the new paired measurements.

No additional key is needed for the offline update. A paid pilot needs a Gemini Developer
API key in `GOOGLE_API_KEY` with access to the chosen current model and Files/Interactions,
plus an explicit spending and attempt limit. The full paired study additionally needs the
exact historical media/question identities and a separate budget. Vertex credentials are
a different integration and are not covered by the existing guard. Keep secrets out of
chat, exports, and Git. No current agentic provider call has been made by this review.
