# Inspect the evidence, change a rule, refresh one decision

The first proof is a local application whose state comes from Pixeltable. It prepares one
generated clip once, lets two requests reuse the same evidence, and makes the effect of a
rule change visible. No provider credentials or model calls are needed.

## Open the workspace

With Python 3.12+ in a virtual environment, from the repository:

```bash
pip install -e ".[workspace]"
run-evidence-workspace
```

Open the printed `http://127.0.0.1:<port>` URL. The launcher owns its listening socket and
new temporary catalog. It clears external database overrides, serves only its generated
media, and accepts bounded JSON policy/refresh requests from the same local origin.
Ctrl-C stops the owned database before removing the temporary home. If shutdown fails,
the home is preserved for inspection. This is a local teaching workspace, with no uploads
or public authentication. See [deployment and recovery](DEPLOYMENT.md).

## Observe the SDK's work

Play the four-second video: a hard cut from dark to bright, accompanied by a continuous
tone. Inspect the four timestamped thumbnails and extracted audio. The graph also stores
two audio segments and two request rows. Both requests initially retain four frames.

1. Set minimum brightness to **128** and apply the rule. Two frames meet the current
   policy. Both saved requests still contain four frames and are marked stale.
2. Refresh **first**. Its stored evidence and decision now use two frames. **Second**
   retains four frames and stays stale.
3. Reload. These states persist in the running catalog. Preparation still has four frames
   and two audio segments; the first request has two evaluations and the second one.
   Source, thumbnail, and audio hashes remain unchanged.

![Actual browser state after the first scoped refresh](images/evidence-workspace.jpg)

The [narrow view](images/evidence-workspace-mobile.jpg) puts source and policy above stored
requests. Browser verification used an approximately 520-pixel layout, not a full device
matrix. The counters record this graph's actual deterministic UDF executions; they are
local teaching diagnostics, not production observability or provider billing.

For the terminal version, run `run-media-demo` with the base installation. It performs
the same sequence and asserts scoped refresh, unchanged media hashes, and zero extra
preparation. The shared SDK operations are:

```python
clips.update({'minimum_brightness': 128.0}, where=clips.clip_id == 'demo')
requests.recompute_columns('evidence', where=requests.request_id == 'first')
```

Query-backed evidence is a stored snapshot. An application's refresh policy is explicit;
a rule change does not silently refresh every request that queried those frames.

## Find the implementation

| Responsibility | Source |
|---|---|
| Generated source video and terminal assertions | [`local_demo.py`](../src/video_benchmark/local_demo.py) |
| Typed video/audio, frame and audio iterator views, thumbnails, requests | [`local_graph.py`](../src/video_benchmark/local_graph.py) |
| Deterministic preparation/review UDFs | [`local_demo_rules.py`](../src/video_benchmark/local_demo_rules.py) |
| HTTP boundary, media allowlist, shutdown, scoped mutations | [`workspace.py`](../src/video_benchmark/workspace.py) |
| Preview, policy, stale results, refresh controls | [`workspace.html`](../src/video_benchmark/web/workspace.html) |
| Optional provider expressions and reusable query evidence | [`schema.py`](../src/video_benchmark/schema.py), [`videomme/schema.py`](../src/video_benchmark/videomme/schema.py) |
| Attempt ledger and managed transport guards | [`admission.py`](../src/video_benchmark/admission.py) |
| Input identity, media/source hashes, installed versions | [`provenance.py`](../src/video_benchmark/provenance.py) |

For a product extension, change the smallest relevant expression, inspect schema changes,
and test which derived fields should refresh. Keep source-media preparation separate from
request-specific decisions. Benchmark catalogs intentionally freeze their definitions;
their `--reset` policy is separate from continuous application migration.

## Check the quality boundary

```bash
run-quality-checks
```

[`quality_cases.json`](../src/video_benchmark/quality_cases.json) has six explicit records.
One reproduces the stored October 9 tone-to-speech/gradual-fade hallucination. The source
contains no speech and a hard cut, so that completed answer fails both supplied checks.
The truthful-description, refusal, missing-audio, empty-output, and invalid-time records
are authored test cases. They are labelled as such and have content hashes.

Completion, refusal/error state, and narrow correctness findings are separate outputs.
These regex checks can miss many false answers and cannot establish general semantic
accuracy, ASR accuracy, or calibrated judgments. Passing means passing the supplied small
checks. A research quality claim needs independently reviewed ground truth and an
appropriate evaluation design.

## Admit paid work deliberately

Both managed comparison CLIs accept:

| Option | Default | Meaning |
|---|---|---|
| `--budget-usd` | 1 | Ceiling for accounted estimates plus unresolved reservations in this ledger |
| `--max-attempts` | 64 | Model sends in this invocation, including retries |
| `--max-media-seconds` | 600 | Maximum duration per input, checked before catalog changes |
| `--ledger` | `results/provider-ledger.sqlite3` | Persistent shared attempt store |
| `--preflight` | off | Inspect selected inputs/settings; no model calls or catalog changes |

Preflight can download a selected sample. It requires configured credentials for selected
paid paths but does not authenticate them. Question text is bounded at 4,000 characters,
frame preparation at 64 frames, and Gemini/Nova output at 4,096 tokens.

The ledger commits a reservation before the actual transport send. Schema application is
inside the guarded scope too. A lost response, timeout, interrupted process, missing usage,
or later cell error cannot free an unresolved reservation. SQLite transactions prevent
concurrent admissions from exceeding the estimated ledger budget. A later invocation has
a new attempt count while retaining the ledger's previous spending and unknown holds.

The guards cover Gemini Developer API `generateContent`, fal's video-understanding queue
submission, and Nova `Converse` on the standard configured AWS region endpoint. Interactions
model POSTs, Vertex, custom model endpoints, unsupported operations, and existing unsupported
transports fail before a model send. Only one managed run owns these process-wide hooks at a time. Direct
SDK scripts outside the context need their own admission policy. SDK/provider upgrades
must rerun the actual offline transport tests.

Gemini and Nova model outputs/usage are recorded before SDK normalization. This preserves
supported raw response fields even when Pixeltable 0.7.16 fails to normalize
`candidates=None`; the cell still fails. Fal's attempt record preserves queue acceptance
and request ID, with a duration-based estimate; the final polled output remains in the
catalog. Request bodies and headers are not recorded; response redaction removes known
environment secrets and URL queries. Keep the ledger access-controlled because model
responses can contain source information.

Reservations use conservative token envelopes and dated prices. They are not invoices or
guaranteed upper bounds on provider charges. Unknown attempts remain held, but more work
can proceed if the budget still fits. Investigate them before explicitly raising limits;
changing ledger files creates a separate budget. Inspect `provider-attempts.json` beside
run exports and retain the SQLite ledger through restarts. It identifies sessions and
attempts, not a complete per-cell response join.

## Make a research change reviewable

For a fresh comparison, retain exact question IDs, answer/options, annotation revision,
video hashes, selected paths, effective prompts/settings, source digest, installed package
versions, and all attempt/export records. Resume only identical accepted inputs. Record
empty/refused/failed answers and unknown costs alongside successes. Use paired video-level
inference where questions share preparation; nonsignificance does not establish equivalence.

The new 4,096-token output cap changes future experimental definitions. Historical 0.7.11
exports and the paper are retained; they are not a fresh paired experiment on 0.7.16.
The same sample count and seed cannot reconstruct the exact historical media/question set.
Agree on spending and duration limits before starting a full rerun. See the
[current agentic comparison protocol](AGENTIC_VIDEO_COMPARISON.md),
[research workflow](WORKFLOW.md#fresh-research-comparisons), and [review](REVIEW.md).

For code changes, install `.[dev,workspace,fal]`, run `pytest -q`, `ruff check src tests
scripts`, `python scripts/schema_apply_smoke.py`, the local lesson and quality checks, and
the read-only paper-table drift check. These checks use generated media and offline SDK
responses. Live provider and full-research validation remain separate experiments.
