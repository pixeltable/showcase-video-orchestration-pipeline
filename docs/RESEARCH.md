# Research Framing: Native vs Modular Video Understanding

Working title: **Native Multimodal Video Understanding vs Modular Keyframe Orchestration: A Fair Multi-Path Benchmark**

## Thesis

While the industry is moving toward **Native Multimodal Models (NMMs)** for deep visual reasoning, **modular keyframe orchestration** remains the most cost-effective production architecture for narrative video Q&A—often cutting inference cost ~50–70% without sacrificing qualitative accuracy on long-form clips (config-dependent; see reference run below).

This repository grounds that debate in a **declarative, reproducible Pixeltable pipeline** (not ad-hoc scripts), with exported `results/<timestamp>/` artifacts for paper appendices. Native baselines include **Gemini**, optional **fal video-understanding**, and optional **Amazon Nova** (Bedrock)—same analysis prompt for fair API comparison.

**Paper:** [docs/paper/paper.md](paper/paper.md) · [docs/paper/paper.pdf](paper/paper.pdf) (build: `python scripts/build_paper_figures.py && ./scripts/build_paper.sh`). Headline five-path export: `results/20260710T040910Z` (`fair_v1_nova_pro`).

---

## Paths mapped to literature

| Path | Architecture | Research term | What it tests |
|------|--------------|---------------|---------------|
| **1** | Full video → Gemini `generate_content` | **Early fusion / NMM** | Native temporal + audiovisual reasoning; highest token cost |
| **2** | Scene-aware keyframes + Gemini transcribe + multimodal synthesis | **Token-efficient orchestration** | Same model as Path 1; smart sampling (QCA/AKS-style) |
| **3** | Scene-aware keyframes + local VLM + WhisperX + 7B synthesis | **Modular late-fusion (fixed)** | Query-aware vision LLM on keyframes; diarized ASR; $0 API cost |
| **4** | Video URL → `fal-ai/video-understanding` (≤120s) | **Native (third-party)** | Alternate NMM API; ~$0.01/5s — often costlier than Gemini |
| **5** | Full video → Bedrock Nova Pro | **Native (AWS)** | Fairer peer than Lite; Bedrock token pricing |

Path 1 and Path 2 use the **same Gemini model** so differences reflect **architecture**, not model choice. Paths 4–5 reuse the same `native_prompt` as Path 1.

**Path 3 stack (current defaults):** Qwen2.5-VL-3B per keyframe → WhisperX diarization (or Whisper fallback without `HF_TOKEN`) → compact frame captions (16×240) → Qwen2.5-7B text synthesis.

---

## Debate 1: Early fusion vs late fusion (Path 1 vs Path 3)

**Late-fusion bottleneck (old Path 3):** BLIP generic captions → text-only LLM never sees pixels. If the caption omits a detail, the model cannot recover it.

**Native advantage (Path 1):** Visual tokens processed alongside text from early transformer layers (*Scaling Laws for Native Multimodal Models*, Apple/CVF 2025; *Toward Native Multimodal Modeling*, arXiv 2605.25343).

**Our fix (new Path 3):** `llama_cpp.create_chat_completion` with `image_url` + `frame_prompt(query)` per keyframe—same orchestration shape as Path 2, local GGUF auto-download from Hugging Face. Scene-aware sampling + compact captions + 7B synthesis close the gap toward native-style structured summaries.

---

## Debate 2: Token budget and cost (Path 1 vs Path 2)

Native video processing burns ~263 tokens/sec (estimated) because of temporal redundancy. Path 2 pays per keyframe image + per audio chunk + one synthesis call.

**Reference finding (Pursuit ~255s, `results/golden/`):** Path 2 ≈ **66% cheaper** than Path 1 (~$0.039 vs ~$0.114) with comparable narrative quality (Chris Gardner interview scene). Lab tune-ab sweeps saw ~50–76% depending on frame budget—treat savings as **config-dependent**.

Related work:
- *QCA: Query- and Content-Aware Keyframe Selection* (July 2026)
- *AKS: Adaptive Keyframe Sampling* (CVPR 2025)
- *ToolMerge: Decomposing Queries into Tool Calls for Long-Video Keyframe Retrieval* (May 2026)

---

## Debate 3: Temporal continuity (Path 2/3 vs Path 1)

*VideoOdyssey* (May 2026) argues discrete frame extraction breaks event chains for ultra-long causal reasoning. Our default **fps sample + scene-cut selection** is a practical compromise—aligned with AKS/QCA rather than dense native encoding. Legacy all-I-frames-per-scene remains available via `SCENE_AWARE_FRAMES=0` and `MAX_VISION_KEYFRAMES=0`.

---

## Video-MME evaluation (phase 2)

Quantitative eval via Hugging Face [`lmms-lab/Video-MME`](https://huggingface.co/datasets/lmms-lab/Video-MME) annotations + `yt-dlp` downloads.

**Dev slice (implemented):** stratified **30 questions** (~10 short / medium / long), Gemini **Paths 1–2**, Path **3 OSS** (local VLM + 7B; **shared Gemini ASR**), Path **5 Nova Lite** (default). fal omitted (120s cap). Shared Path 2/3 frame prep once per video; per-question MCQ; exact-match A–D + `cost_per_correct`.

```bash
pip install -e ".[videomme]"
./scripts/run_videomme_dev.sh          # or: run-videomme-dev
# subset: run-videomme-dev --paths 1,2,5 --skip-oss
# sample + download only (no model spend):
run-videomme-dev --sample-only --fresh-sample
```

Exports land in `results/videomme-dev/<timestamp>/`. Manifest: `assets/videomme/sample_manifest.json`. Reference fixed Gemini-only run: `results/videomme-dev/20260711T025812Z`. Four-path (1/2/3/5) run: `results/videomme-dev/20260711T052512Z` (+ `COMPARISON.md`).

**Full set (900 V / 2700 Q):** still planned — do not run without an explicit budget.

---

## Experiment roadmap

| Experiment | Status | Metrics |
|------------|--------|---------|
| Pursuit qualitative (255s) | Done | Narrative + cost |
| Pursuit golden export | Done — `results/golden/` (`fair_v1_nova_pro`) | Showcase + paper appendix |
| Tune A/B (lab only) | Done — not part of showcase story | Heuristic sweeps under `results/tune-ab/` |
| Video-MME dev (30 Q) | Done — Paths 1,2,3,5; see `results/videomme-dev/20260711T052512Z` | MCQ accuracy + cost/correct |
| Video-MME Nova S3 / long-byte fix | Gap — Bedrock ValidationException on most inline uploads | S3 URI or size gate |
| Video-MME full (900 V) | Planned | Stratified accuracy + cost/correct |

---

## Bibliography (selected)

- Fu et al., *Video-MME*, CVPR 2025
- *Toward Native Multimodal Modeling: A Roadmap*, arXiv 2605.25343 (May 2026)
- *Scaling Laws for Native Multimodal Models*, Apple/CVF 2025
- *VideoOdyssey: Ultra-Long-Context Omni-Modal Video Understanding*, May 2026
- *ToolMerge*, May 2026
- *QCA: Query- and Content-Aware Keyframe Selection*, July 2026
- *AKS: Adaptive Keyframe Sampling*, CVPR 2025
