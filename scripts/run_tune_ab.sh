#!/usr/bin/env bash
# Run three tagged benchmark configurations for quality tuning A/B comparison.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
source .venv/bin/activate

if ! python -c "import whisperx" >/dev/null 2>&1; then
  pip install -e ".[whisperx]" -q
fi

if [[ -z "${HF_TOKEN:-}" && -z "${HUGGING_FACE_HUB_TOKEN:-}" ]]; then
  echo "Warning: HF_TOKEN not set — Path 3 WhisperX diarization runs will fail." >&2
  echo "Set HF_TOKEN in .env for pyannote/speaker-diarization-3.1 acceptance." >&2
  WHISPERX_ASR="${WHISPERX_ASR:-whisper}"
else
  WHISPERX_ASR="${WHISPERX_ASR:-whisperx}"
fi

VIDEO="${1:-assets/pursuit-of-happiness.mp4}"
EXPORT_DIR="${2:-results/tune-ab}"

mkdir -p "$EXPORT_DIR"

run_case() {
  local tag="$1"
  shift
  echo "=== Running tune case: $tag ==="
  env BENCHMARK_TUNE_TAG="$tag" "$@" \
    run-benchmark --video "$VIDEO" --reset --export "$EXPORT_DIR"
}

# 1) Baseline — legacy-ish settings (whisper ASR, 12 uniform frames)
run_case baseline \
  OSS_ASR=whisper \
  MAX_VISION_KEYFRAMES=12 \
  FRAME_CONTEXT_MAX_ENTRIES=12 \
  SCENE_AWARE_FRAMES=0 \
  OSS_SYNTH_MAX_TOKENS=768

# 2) ASR + prompts + synth — WhisperX diarization, upgraded prompts, longer OSS output
run_case asr_prompts_synth \
  OSS_ASR="$WHISPERX_ASR" \
  MAX_VISION_KEYFRAMES=12 \
  FRAME_CONTEXT_MAX_ENTRIES=12 \
  SCENE_AWARE_FRAMES=0 \
  OSS_SYNTH_MAX_TOKENS=1536

# 3) Scene-aware frames on top of run 2 settings
run_case scene_aware \
  OSS_ASR="$WHISPERX_ASR" \
  SCENE_AWARE_FRAMES=1 \
  VISION_SAMPLE_KEYFRAMES=24 \
  FRAME_SELECT_BUDGET=16 \
  FRAME_CONTEXT_MAX_ENTRIES=16 \
  OSS_SYNTH_MAX_TOKENS=1536

python scripts/score_tune_runs.py "$EXPORT_DIR"
