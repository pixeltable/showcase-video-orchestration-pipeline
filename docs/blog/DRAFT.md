# Blog draft: Take back control of video understanding

> Status: draft for Pixeltable blog / companion to the paper.  
> Repo: [pixeltable/showcase-video-orchestration-pipeline](https://github.com/pixeltable/showcase-video-orchestration-pipeline) · Paper: [docs/paper/paper.md](../paper/paper.md) · Pixeltable 0.7.8 TableModel CLI

## Working title

**Own the stack: why modular video pipelines still beat opaque native APIs on cost—and how Pixeltable makes them reproducible**

## Hook

Vendors push “just send the whole video to the model.” That works—until the bill arrives, the API caps you at two minutes, or you cannot see *which* frames drove the answer. Modular orchestration (keyframes + ASR + synthesis) looks old-fashioned until you measure it fairly against the same model.

## Thesis (one paragraph)

On a fixed long-form narrative clip, **same-model Gemini orchestration costs ~66% less than native full-video Gemini** while matching or beating narrative completeness. Pixeltable turns that pipeline into a **declarative catalog**: insert a video, recompute computed columns, export machine-readable costs and answers. You choose native, orchestrated, or fully open-source—without rewriting glue scripts.

## What readers should feel

- **Power:** Frames, transcripts, and synthesis prompts are inspectable stages—not a black box.
- **Control:** Change frame budget or swap Path 3 to local GGUFs without changing the evaluation harness.
- **Honesty:** Optional natives (fal, Nova) are baselines with documented caps and failure modes—not co-equal heroes.

## Outline

1. **The industry story** — early-fusion NMMs vs production late fusion (link Apple/CVF scaling + roadmap papers).
2. **The fairness problem** — different models, prompts, and cherry-picked clips make demos incomparable.
3. **Five paths, one catalog** (4–5 are optional natives)
   - Path 1: native Gemini video
   - Path 2: scene-aware keyframes + `gemini.transcribe` + multimodal synth
   - Path 3: Qwen2.5-VL + WhisperX + Qwen2.5-7B
4. **Headline result** — Pursuit ~255s: $0.114 vs $0.039; Path 2 hits unpaid-internship / punchline / “tonight”.
5. **Video-MME sneak peek** — objective MCQ slice: orchestration stays far cheaper per correct; OSS trails; Nova needs S3 for long clips.
6. **How to try it** — `pip install -e ".[demo]"` → `run-benchmark --paths 1,2 --reset` → open `REPORT.md`.
7. **Customize** — point to `examples/orchestrated.env` and `examples/oss.env`.
8. **CTA** — star the repo, read the paper, bring your own video.

## Pull quotes (from golden export)

- Cost: “Path 2 **$0.039** vs Path 1 **$0.114** on the same Gemini model.”
- Control: “Insert a video into Pixeltable; the computed graph is the experiment.”
- Caveat: “fal’s 120s cap and $/5s pricing are teaching tools—not free wins.”

## Assets to attach

- Figure: cost bars from `docs/paper/figures/`
- Screenshot: `docs/showcase.html` three-column excerpt
- Link: `results/golden/REPORT.md`

## What not to say

- Do not claim Video-MME full 900V is done.
- Do not present Nova Video-MME numbers without the Bedrock ValidationException caveat.
- Do not lead with fal or tune-ab lab history.
