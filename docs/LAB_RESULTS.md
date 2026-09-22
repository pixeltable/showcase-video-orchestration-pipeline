# Lab results (not the public showcase)

Committed public artifacts:

| Path | Role |
|------|------|
| [`results/golden/`](../results/golden/) | Headline Pursuit export (`fair_v1_nova_pro`) |
| Local `results/<timestamp>/` | Gitignored experiment dumps |
| Local `results/tune-ab/` | Frame/ASR/synth sweeps — lab tooling only |
| Local `results/videomme-dev/` | Video-MME exports (**gitignored**; GitHub clones will not have these timestamp dirs) |

## Video-MME pointers (local)

| Run | Status |
|-----|--------|
| `20260711T012446Z` | **Invalid** — cross-video ASR/frame bleed before query scoping. Do not cite. |
| `20260711T025812Z` | Gemini Paths 1–2 fixed (reference for paper figures). |
| `20260711T052512Z` | Four-path (1/2/3/5) + `COMPARISON.md`; Nova mostly Bedrock ValidationException. |

## Demoted from the front door

- Tune A/B (`scripts/run_tune_ab.sh`) — keep for implementers; not a README recipe.
- fal / Nova — optional provider baselines; 120s fal cap and Nova byte limits are caveats.
- Silence-aware audio splitter modes — unused under `AUDIO_SPLIT_MODE=full`; do not advertise.
