# Showcase review - 2026-10-08

This review covers the current local work in `pixeltable/showcase-video-orchestration-pipeline`, including the TableModel rewrite. Pre-existing changes and recorded experiment exports were preserved. The SDK pin and local environment were upgraded from **0.7.11 to 0.7.15**, the latest stable release reported by the live [PyPI JSON endpoint](https://pypi.org/pypi/pixeltable/json) on the review date. Initial verification made no provider model calls or user-catalog migrations; the latest-release/live follow-up below records subsequent isolated provider calls.

The application is a useful SDK showcase: typed media, iterator views, computed provider calls, materialized query-backed evidence, and inspectable intermediate results. The developer entry point now demonstrates that graph with a real generated clip and no credentials. The research comparison remains exploratory evidence about a specific model and sample. Its artifacts are recordings from 0.7.11, not a new benchmark on 0.7.15 or 0.7.16.

## Correctness findings and changes

| Priority | Finding | Resolution and evidence |
|----------|---------|-------------------------|
| P1 | Cached Gemini tokens without a modality breakdown were subtracted from a nonexistent text bucket. A 1,000-video-token call with 500 cached tokens priced at $0.000315 instead of $0.000165. | `pricing.py` allocates the aggregate cache only when all input modalities share the same price pair. Ambiguous mixed audio/video allocation is an accounting error. A regression checks the exact amounts. The independent review found no affected records in committed exports, so historical costs were not rewritten. |
| P1 | Missing token usage made a successful paid call look free. A valid answer could export cost zero even when usage or cost computation failed. | Missing usage raises a visible accounting error. Pursuit and Video-MME preserve valid answers, report nullable totals, distinguish unknown-cost counts from provider failures, and expose known partial subtotals explicitly. Integration tests cover native calls, captions, transcription, and ambiguous cache allocation. |
| P1 | Question-level Wilson intervals and McNemar tests assumed independence although three questions share each video. Missing outcomes also could use a different bootstrap denominator. | Accuracy and difference intervals now resample whole videos, and paired tests exchange whole-video path labels with exact integer enumeration. Missing answers count as wrong in every denominator. Wilson/McNemar remain labeled diagnostics; comparisons are exploratory and unadjusted. Figures and paper were reanalysed from fixed predictions, with original exports retained. |
| P1 | Expression-only schema comparison could miss edited UDF bodies or prompts while claiming frozen experimental definitions. | The graph stores a definition digest covering computation source, configuration, selected paths, and SDK version. A mismatching digest requires a new benchmark catalog. Tests confirm unchanged repeated application is a no-op and changed definitions are rejected. |
| P1 | A Gemini Files API cleanup failure replaced a successful transcription response and could trigger another paid call. File processing polling had no deadline. | Upload and processing are bounded. Deletion is best effort with a timeout and warning; it preserves both a paid response and a primary model error. Tests simulate cleanup failure and a permanently processing upload. |
| P2 | Invalid inputs could reach downloads or catalog reset before validation; zero repeats silently became one run. | Numeric configuration and CLI inputs are validated before side effects. Missing media is checked before reset, Video-MME credentials before downloading, and an entirely disabled path set cannot report success. Tests verify reset/download ordering. |
| P2 | Exports named a commit and file path but did not identify uncommitted source, dependency versions, or media bytes. Annotations followed a mutable dataset revision. | New manifests record Git dirty state, source digest and package versions; media is SHA-256 fingerprinted. Video-MME annotations are pinned to revision `ead1408f75b618502df9a1d8e0950166bf0a2a0b`; sample manifests include an annotation digest and only reuse the matching revision. |
| P2 | The inspection notebook assumed specific paths and re-priced old runs using current environment settings. Its launcher supplied an unsupported kernel-install flag. | The notebook skips absent stages, reads the selected run's exported cost/configuration snapshot, and scopes errors to that run. Native-only and modular notebook execution is tested offline with no additional calls. The unsupported flag was removed. |
| P2 | The upgrade watch installed a new SDK without resolving its dependencies; schema coverage omitted the WhisperX branch. | The watch now resolves newer SDK dependencies and runs the local media graph. Schema smoke applies all supported path combinations and Whisper, WhisperX, and Gemini ASR declarations twice in an isolated home. |
| P2 | Prominent prose conflated response-based estimates with invoices, phrase checks with quality, and nonsignificance with equivalence. | README, workflow, paper, blog, and showcase state cost exclusions, coverage differences, sample and inference limitations, and historical SDK provenance. The paper PDF was rebuilt and visually checked. |

## Follow-up under the five-step principles - 2026-10-09

The smallest additional scope was one complete developer loop and three existing correctness boundaries. The provider graphs, scientific sample, SDK pin, and historical records were retained; no service or general provider framework was added.

- **Immutable accepted inputs.** Resuming previously matched primary keys only. Video-MME now stores input and media identities at acceptance and preflights both entire input sets before inserting anything. Changed question, options, answer, video link, annotation revision, or same-path media replacement is rejected before new provider calls. A row without its original identity is also rejected. Identical bytes at a different path resume without calls; adding a question computes only its answer. The annotation revision participates in the frozen catalog definition.
- **Known spend survives unknown totals.** A question with unknown shared preparation cost previously lost its known answer cost from the summary subtotal. A small common accounting policy now keeps nullable complete totals and separate known response/list subtotals across Pursuit and Video-MME. Preparation is allocated once across exported questions even if an answer also has unknown usage. Stored graph total columns likewise remain unknown when any paid stage is unknown. Historical records lacking subtotal fields retain their recorded costs through an explicit fallback.
- **Validate effective choices.** Both CLIs select paths before configuration validation. Inactive settings use stable defaults, so unrelated OSS/frame knobs and credential-disabled Nova settings do not gate native runs. Local ASR validates Gemini only when selected; Video-MME correctly validates its forced Gemini ASR. `--paths` is the main selection interface, and skip aliases remain compatible. Invalid active settings fail before media acquisition, catalog reset, or schema application.
- **One owned decision loop.** The local demo prepares four frames and two audio segments, applies a brightness rule, and reuses preparation for two requests. A policy change leaves query snapshots stale; explicit recomputation refreshes only the first request's evidence and decision. Assertions verify four preparation executions, the intended three request evaluations, and unchanged source/frame/audio hashes. Its two UDFs live in an importable module, as the SDK requires.

The follow-up's targeted checks and final offline suite use generated local media, temporary catalogs, and fake provider responses. They establish input, accounting, and query lifecycle behavior, not live-provider reliability or model quality. Final validation is recorded below.

## Remaining SDK boundary

**Pixeltable 0.7.15 and 0.7.16 still lose a Gemini response whose `candidates` field is `None`.** Its built-in `generate_content` iterates `result.get('candidates', [])`, which raises `TypeError` for that value. The cell records the error, but the refusal response and reported usage are not stored. This was reproduced offline against the installed release. The application now keeps its cost unknown and does not automatically retry this deterministic parsing failure.

Fixing the cell correctly belongs in the SDK's response normalization (`result.get('candidates') or []`), followed by validation of the stored refusal response and usage. The October 10 managed CLI guard now records supported response fields and usage before normalization, so new guarded refusals remain inspectable in the separate attempt ledger even when the cell fails. Direct SDK calls outside that guard retain the upstream boundary. No native video serialization, Files API handling, or private Pixeltable provider getter was duplicated. Historical refusals cannot be repaired from existing exports.

## Research interpretation

Reanalysis of the same 123 recorded questions from 41 videos preserves all point accuracies and recorded costs:

| Path | Correct | Accuracy | 95% video-cluster percentile interval |
|------|--------:|---------:|--------------------------------------:|
| Native Gemini | 98 / 123 | 79.7% | [70.7%, 87.8%] |
| Native Gemini, low resolution | 103 / 123 | 83.7% | [74.8%, 91.1%] |
| Orchestrated Gemini | 98 / 123 | 79.7% | [71.5%, 87.0%] |
| Nova Lite | 72 / 123 | 58.5% | [50.4%, 66.7%] |

Paired video-level p-values are 0.273 for native versus low resolution, 1.000 for native versus orchestrated, and 0.498 for low resolution versus orchestrated. These do not demonstrate equivalent accuracy. The videos were locally available, not a random draw of the full benchmark. Percentile intervals can collapse on small all-correct/all-wrong strata. Provider baselines also differ in coverage: fal sees only the first 120 seconds and Nova ignores audio. The Pursuit checks count clip-specific phrases and cannot establish semantic quality or speaker correctness.

All historical costs are estimates from the final stored responses at dated rates. They exclude unrecorded retries and interrupted attempts, lost refusal usage, local compute, storage, and egress. `numbers.json` and figures use corrected inference over saved predictions; original result directories retain their recorded definitions and version metadata.

## Verification and boundaries

- Pixeltable 0.7.15 installed through the declared package dependency; pin check and dependency consistency check passed.
- Final validation on 2026-10-09: **115 tests passed**. The offline suite covers provider/accounting failures, input identity conflicts before side effects, effective configuration, graph execution, evidence reuse and scoped refresh, batch-scoped retry, native/modular notebook execution, generated research tables, and renderer security/provenance checks. The 26 warnings are the SDK's upstream scene-detection deprecation warning.
- Real isolated TableModel application passed twice for every exercised path set, including all three ASR declarations. No provider rows were inserted by that smoke check.
- `run-media-demo` generated a real four-second MP4, verified four timestamped 128x96 thumbnails and two audio segments, and shared preparation across two requests. Changing the rule left both request snapshots stale; explicitly refreshing the first recomputed its evidence and decision only. Preparation counts and source/frame/audio hashes remained unchanged. The installed entrypoint and module entrypoint passed with no provider calls, and their temporary catalogs were removed.
- Both command-line help checks and lint passed. The research figures regenerated from saved exports. Repeated README and paper result tables now derive from `numbers.json`; a read-only drift check runs in CI and before PDF compilation. Four focused renderer tests cover unknown costs, malformed markers, read-only checks, and preserving PDF captions. The 14-page PDF compiled and passed visual inspection of all pages, including detailed table and figure checks; small TeX overfull warnings had no visible defect.

Before the live follow-up below, Gemini, fal, and Bedrock transport, billing, model availability, and quota behavior had not been exercised. The small subsequent calls verify only the scope recorded below. Local GGUF/WhisperX model downloads, GPU inference, and quality were not validated. Deployment, authentication, upload quotas, admission control, concurrency load, and invoice reconciliation are outside this local SDK/research showcase. Existing real catalogs were not changed; the upgraded frozen definition will request a rebuild, and saved runs should be exported before any reset.

## Developer path

Start with `run-media-demo`, inspect `local_demo.py` and its deterministic rules in `local_demo_rules.py`, then change the local review policy. The assertions show reuse and deliberate snapshot refresh. The optional provider/research graphs extend this same SDK model; their extension points are in [WORKFLOW.md](WORKFLOW.md). Provider choices and transformations remain ordinary expressions. Query-agnostic preparation can serve many request rows, as Video-MME demonstrates, while frozen benchmark catalogs retain strict definition and input identity checks.

## Latest-release and live validation - 2026-10-09

The follow-up updated the dependency pin and installed environment to **0.7.16**, released on October 9. The offline suite passed **116 tests** with 26 upstream scene-detection warnings. Dependency/pin consistency and twice-applied isolated all-path schema checks passed. Inspection of the newly installed Gemini wrapper confirmed the unchanged `candidates=None` boundary above.

Existing Gemini and Hugging Face credentials authenticated and passed the pyannote model gates. AWS authenticated, reported Nova Pro available in us-east-1, and completed a real invocation. Fal also completed a real invocation. No additional provider key or access grant was required for the cloud smoke paths.

Two new temporary catalogs processed the same generated four-second, 64x48 clip: a dark-to-bright visual cut and a 440 Hz tone, with no speech. Paths 1, 1L, and 2 completed eight observed Gemini requests without errors, using four caption frames, a three-frame evidence budget, and two synthesis images. Separate Paths 4 and 5 completed fal and Nova Pro calls. All five returned answers and accounted costs; the combined response-accounted estimate was **$0.0178289**, including fal's duration-based $0.01 estimate. This is not a reconciled invoice. Stored provider responses, manifests, and attempt logs remain in new local `results/live-validation/` exports; a compact public record is [validation/2026-10-09.json](validation/2026-10-09.json). Temporary catalogs were removed and existing catalogs were untouched.

Successful execution did not establish quality: Path 2's ASR invented “mm.” from a tone, and synthesis repeated it. Native Gemini and fal also described the tone as ringing. The smoke check validates current transport, persistence, and usage accounting, not truthful ASR, calibrated audio classification, or research accuracy. Nova's path omits audio by design. No model prompt or score was changed to conceal these observations.

The published 41-video/123-question comparison, local GGUF Path 3, GPU execution, quota/load behavior, and invoice reconciliation remain unvalidated on the new release. A full paired research rerun needs a separate spending limit and the exact published question/media identities rather than a new sample with the same count/seed. Historical result exports, figures, and headline statistics remain unchanged.

## Interactive ownership and guarded admission - 2026-10-10

The local browser workspace and command-line lesson now share `LocalMediaGraph`: one
generated source, typed video/audio, frame and audio iterator views, thumbnails, a business
rule, and two stored request decisions. The browser previews real prepared media and
reads actual SDK state. Applying brightness 128 leaves both query snapshots stale;
refreshing first changes only its evidence/decision. Source/preparation hashes and four
preparation executions remain unchanged. The [walkthrough](WALKTHROUGH.md) maps controls
to the declarations and explains explicit refresh.

Both paid CLIs now inspect every media input before catalog mutations and run schema
application inside a managed admission context. An independent SQLite attempt ledger
commits a reservation before each supported transport send, captures available model
response/usage before SDK normalization, and retains pending/unknown reservations across
restarts. Limits cover estimated cumulative ledger spending, sends per invocation, input
duration, question/frame preparation, and Gemini/Nova output. The 4,096-token output cap
changes future definitions; historical comparisons were not rerun or relabelled.

Review caught and corrected schema-triggered calls outside the guard, config-derived and
warmed Bedrock clients bypassing default-session hooks, Vertex/custom endpoints passing
through without reservations, and unsupported Bedrock operations. The final adapters
instrument actual HTTPX and botocore sends while retaining Pixeltable's provider UDFs.
Offline tests use real Google/fal/boto3 clients with substituted network transports.
No private Pixeltable provider getter or media serialization is replaced.

Six labelled quality records separate completion from narrow correctness checks. One
reproduces the recorded tone/speech/gradual-fade hallucination; five are authored boundary
cases. These diagnostics can miss arbitrary false answers and are not a model-quality
benchmark. Exact case hashes, source identity, and package versions accompany their output.

| Check | Observed result |
|---|---|
| Full offline suite | **147 tests passed**, with 28 upstream FastAPI/scene-detection deprecation warnings. Includes real SDK transport interception, atomic reservations, unknown holds, retries, warmed/bearer Bedrock clients, unsupported endpoints, actual graph HTTP state, origin/host/media boundaries, oversized/misreported bodies, labelled quality records, and existing research/accounting checks. |
| Schema application | All existing Pursuit and Video-MME path sets and ASR declarations applied twice in an isolated home; no rows/provider calls. |
| Real local lesson | Four frames/two audio segments, only first request refreshed, three total request evaluations, unchanged media hashes; owned database stopped before cleanup. |
| Browser verification | Actual playback, loaded frame/audio media, rule mutation, scoped refresh and reload persistence passed at desktop and an approximately 520-pixel width. Captures are in `docs/images/`; not a full device matrix. |
| Cold recovery | [Stopped-copy same-path restore](validation/2026-10-10-restore.json) preserved 1 clip, 4 frames, 2 audio segments, 2 requests, and hashes. A new process refreshed second only with zero preparation calls. Its frozen source hashes identify that drill; later launcher isolation/cleanup changes leave the shared graph unchanged. |
| Release checks | Lint, dependency consistency, pin, installed CLI help/quality entrypoints, read-only result-table checks, and renderer checks passed. No current paid model calls, user-catalog mutations, research/PDF rewrites, or hosted deployment. |

The workspace is loopback-only and temporary, with generated inputs, same-origin mutations,
an actual-byte body bound, and a media allowlist. A failed database shutdown preserves its
home. Tests and isolated launchers explicitly clear external database overrides.
[DEPLOYMENT.md](DEPLOYMENT.md) covers authentication, private writer/database topology,
secrets, retention, and backup responsibilities for an actual deployment.

Admission uses dated price assumptions and conservative envelopes, not an invoice ceiling.
Unknown attempts remain held but do not stop other work if its reservation still fits.
Fal's ledger records acceptance/request ID plus a duration estimate; final polled answers
remain in the catalog. The ledger identifies sessions/attempts, not a complete per-cell
response join. Direct SDK calls outside the managed context do not inherit these guards.
Provider or SDK upgrades need the transport regressions again. A full paid paired research
rerun, live verification of the new guards, public auth/tenancy, load behavior, and
invoice reconciliation remain separate validation work.
