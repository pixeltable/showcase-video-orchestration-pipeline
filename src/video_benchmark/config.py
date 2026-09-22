"""Environment configuration for the five-path benchmark."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_QUERY = (
    'Summarize the main activities, speakers, and visual events in this video.'
)
PURSUIT_VIDEO_URL = (
    'https://raw.githubusercontent.com/pixeltable/pixeltable/main/docs/resources/'
    'The-Pursuit-of-Happiness.mp4'
)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
ASSETS_DIR = PROJECT_ROOT / 'assets'
DEFAULT_SAMPLE = ASSETS_DIR / 'pursuit-of-happiness.mp4'

AUDIO_SPLIT_FULL_DURATION_SEC = 1_000_000.0
DEFAULT_AUDIO_CHUNK_MAX_BYTES = 24 * 1024 * 1024


@dataclass(frozen=True)
class BenchmarkConfig:
    gemini_model: str
    oss_backend: str
    oss_vision_repo_id: str
    oss_vision_repo_filename: str
    oss_vision_mmproj_repo_filename: str
    oss_vision_chat_format: str | None
    oss_synth_repo_id: str
    oss_synth_repo_filename: str
    oss_synth_max_tokens: int
    oss_frame_context_max_entries: int
    oss_frame_insight_max_chars: int
    oss_vision_model: str
    ollama_host: str | None
    whisper_model: str
    whisperx_model: str
    whisperx_diarization_model: str
    whisperx_min_speakers: int | None
    whisperx_num_speakers: int | None
    oss_asr: str
    audio_split_mode: str
    audio_chunk_duration_sec: float
    audio_chunk_max_bytes: int
    gemini_vision_mode: str
    gemini_vision_batch_size: int
    max_vision_keyframes: int
    vision_sample_keyframes: int
    vision_reference_duration_sec: float
    frame_context_max_entries: int
    scene_aware_frames: bool
    frame_select_budget: int
    gemini_synth_max_images: int
    scene_detect_threshold: float
    min_segment_duration: float
    segment_fallback_window_sec: float
    enable_fal: bool
    fal_video_url: str
    fal_detailed_analysis: bool
    enable_nova: bool
    nova_model_id: str
    nova_video_s3_uri: str
    nova_input_usd_per_1m: float
    nova_output_usd_per_1m: float
    benchmark_reset: bool
    benchmark_tune_tag: str
    default_query: str = DEFAULT_QUERY


def load_dotenv(env_path: Path | None = None) -> None:
    path = env_path or PROJECT_ROOT / '.env'
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            key, _, value = line.partition('=')
            os.environ.setdefault(key.strip(), value.strip())


def _optional_int(name: str) -> int | None:
    raw = os.environ.get(name, '').strip()
    if not raw:
        return None
    return int(raw)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {'1', 'true', 'yes'}


def _fal_enabled() -> bool:
    if os.environ.get('ENABLE_FAL') is not None:
        return _env_bool('ENABLE_FAL', False)
    return bool(os.environ.get('FAL_KEY') or os.environ.get('FAL_API_KEY'))


def _nova_enabled() -> bool:
    if os.environ.get('ENABLE_NOVA') is not None:
        return _env_bool('ENABLE_NOVA', False)
    if os.environ.get('AWS_BEARER_TOKEN_BEDROCK') or os.environ.get('BEDROCK_API_KEY'):
        return True
    if os.environ.get('AWS_ACCESS_KEY_ID') and os.environ.get('AWS_SECRET_ACCESS_KEY'):
        return True
    return False


def load_config() -> BenchmarkConfig:
    load_dotenv()
    # fal_client.upload_file expects FAL_KEY; Pixeltable accepts FAL_API_KEY.
    if not os.environ.get('FAL_KEY') and os.environ.get('FAL_API_KEY'):
        os.environ['FAL_KEY'] = os.environ['FAL_API_KEY']
    chat_fmt = os.environ.get('OSS_VISION_CHAT_FORMAT', 'qwen2.5-vl').strip()
    audio_mode = os.environ.get('AUDIO_SPLIT_MODE', 'full').strip().lower()
    vision_mode = os.environ.get('GEMINI_VISION_MODE', 'per_frame').strip().lower()
    scene_aware = os.environ.get('SCENE_AWARE_FRAMES', '1').strip().lower() in {'1', 'true', 'yes'}
    max_kf = int(os.environ.get('MAX_VISION_KEYFRAMES', '12'))
    sample_kf = int(os.environ.get('VISION_SAMPLE_KEYFRAMES', '24' if scene_aware else str(max_kf)))
    frame_cap = int(os.environ.get('FRAME_CONTEXT_MAX_ENTRIES', '16' if scene_aware else '12'))
    select_default = '16' if scene_aware else str(frame_cap)
    select_budget = int(os.environ.get('FRAME_SELECT_BUDGET', select_default))
    oss_asr_raw = os.environ.get('OSS_ASR', 'whisperx').strip().lower()
    if oss_asr_raw not in {'whisper', 'whisperx', 'gemini'}:
        raise ValueError(
            f'OSS_ASR must be whisper, whisperx, or gemini (got {oss_asr_raw!r})'
        )
    hf_token = os.environ.get('HF_TOKEN') or os.environ.get('HUGGING_FACE_HUB_TOKEN')
    if oss_asr_raw == 'whisperx' and not hf_token:
        oss_asr = 'whisper'
    else:
        oss_asr = oss_asr_raw
    nova_in = os.environ.get('NOVA_INPUT_USD_PER_1M', '').strip()
    nova_out = os.environ.get('NOVA_OUTPUT_USD_PER_1M', '').strip()
    return BenchmarkConfig(
        gemini_model=os.environ.get('GEMINI_MODEL', 'gemini-2.5-flash'),
        oss_backend=os.environ.get('OSS_BACKEND', 'llama_cpp').strip().lower(),
        oss_vision_repo_id=os.environ.get(
            'OSS_VISION_REPO_ID', 'unsloth/Qwen2.5-VL-3B-Instruct-GGUF'
        ),
        oss_vision_repo_filename=os.environ.get(
            'OSS_VISION_REPO_FILENAME', 'Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf'
        ),
        oss_vision_mmproj_repo_filename=os.environ.get(
            'OSS_VISION_MMPROJ_REPO_FILENAME', 'mmproj-F16.gguf'
        ),
        oss_vision_chat_format=chat_fmt if chat_fmt else None,
        oss_synth_repo_id=os.environ.get(
            'OSS_SYNTH_REPO_ID', 'Qwen/Qwen2.5-7B-Instruct-GGUF'
        ),
        oss_synth_repo_filename=os.environ.get(
            'OSS_SYNTH_REPO_FILENAME', 'qwen2.5-7b-instruct-q3_k_m.gguf'
        ),
        oss_synth_max_tokens=int(os.environ.get('OSS_SYNTH_MAX_TOKENS', '2048')),
        oss_frame_context_max_entries=int(os.environ.get('OSS_FRAME_CONTEXT_MAX_ENTRIES', '16')),
        oss_frame_insight_max_chars=int(os.environ.get('OSS_FRAME_INSIGHT_MAX_CHARS', '240')),
        oss_vision_model=os.environ.get('OSS_VISION_MODEL', 'llava:13b'),
        ollama_host=os.environ.get('OLLAMA_HOST'),
        whisper_model=os.environ.get('WHISPER_MODEL', 'small'),
        whisperx_model=os.environ.get('WHISPERX_MODEL', 'small.en'),
        whisperx_diarization_model=os.environ.get(
            'WHISPERX_DIARIZATION_MODEL', 'pyannote/speaker-diarization-3.1'
        ),
        whisperx_min_speakers=_optional_int('WHISPERX_MIN_SPEAKERS') or 2,
        whisperx_num_speakers=_optional_int('WHISPERX_NUM_SPEAKERS'),
        oss_asr=oss_asr,
        audio_split_mode=audio_mode,
        audio_chunk_duration_sec=float(os.environ.get('AUDIO_CHUNK_DURATION_SEC', '10.0')),
        audio_chunk_max_bytes=int(
            os.environ.get('AUDIO_CHUNK_MAX_BYTES', str(DEFAULT_AUDIO_CHUNK_MAX_BYTES))
        ),
        gemini_vision_mode=vision_mode,
        gemini_vision_batch_size=int(os.environ.get('GEMINI_VISION_BATCH_SIZE', '6')),
        max_vision_keyframes=max_kf,
        vision_sample_keyframes=sample_kf,
        vision_reference_duration_sec=float(
            os.environ.get('VISION_REFERENCE_DURATION_SEC', '260.0')
        ),
        frame_context_max_entries=frame_cap,
        scene_aware_frames=scene_aware,
        frame_select_budget=select_budget,
        gemini_synth_max_images=int(os.environ.get('GEMINI_SYNTH_MAX_IMAGES', '8')),
        scene_detect_threshold=float(os.environ.get('SCENE_DETECT_THRESHOLD', '20.0')),
        min_segment_duration=float(os.environ.get('MIN_SEGMENT_DURATION', '1.0')),
        segment_fallback_window_sec=float(os.environ.get('SEGMENT_FALLBACK_WINDOW_SEC', '10.0')),
        enable_fal=_fal_enabled(),
        fal_video_url=os.environ.get('FAL_VIDEO_URL', '').strip(),
        fal_detailed_analysis=_env_bool('FAL_DETAILED_ANALYSIS', False),
        enable_nova=_nova_enabled(),
        nova_model_id=os.environ.get('NOVA_MODEL_ID', 'amazon.nova-pro-v1:0'),
        nova_video_s3_uri=os.environ.get('NOVA_VIDEO_S3_URI', '').strip(),
        nova_input_usd_per_1m=float(nova_in) if nova_in else -1.0,
        nova_output_usd_per_1m=float(nova_out) if nova_out else -1.0,
        benchmark_reset=os.environ.get('BENCHMARK_RESET', '').strip() == '1',
        benchmark_tune_tag=os.environ.get('BENCHMARK_TUNE_TAG', '').strip(),
    )


def config_manifest_dict(config: BenchmarkConfig) -> dict:
    """Serializable config for results/manifest (no secrets)."""
    return {
        'benchmark_tune_tag': config.benchmark_tune_tag or None,
        'gemini_model': config.gemini_model,
        'oss_backend': config.oss_backend,
        'oss_vision_repo_id': config.oss_vision_repo_id,
        'oss_vision_repo_filename': config.oss_vision_repo_filename,
        'oss_vision_mmproj_repo_filename': config.oss_vision_mmproj_repo_filename,
        'oss_vision_chat_format': config.oss_vision_chat_format,
        'oss_synth_repo_id': config.oss_synth_repo_id,
        'oss_synth_repo_filename': config.oss_synth_repo_filename,
        'oss_synth_max_tokens': config.oss_synth_max_tokens,
        'oss_frame_context_max_entries': config.oss_frame_context_max_entries,
        'oss_frame_insight_max_chars': config.oss_frame_insight_max_chars,
        'oss_vision_model': config.oss_vision_model,
        'whisper_model': config.whisper_model,
        'whisperx_model': config.whisperx_model,
        'whisperx_diarization_model': config.whisperx_diarization_model,
        'whisperx_min_speakers': config.whisperx_min_speakers,
        'whisperx_num_speakers': config.whisperx_num_speakers,
        'oss_asr': config.oss_asr,
        'audio_split_mode': config.audio_split_mode,
        'audio_chunk_duration_sec': config.audio_chunk_duration_sec,
        'audio_chunk_max_bytes': config.audio_chunk_max_bytes,
        'gemini_vision_mode': config.gemini_vision_mode,
        'gemini_vision_batch_size': config.gemini_vision_batch_size,
        'max_vision_keyframes': config.max_vision_keyframes,
        'vision_sample_keyframes': config.vision_sample_keyframes,
        'vision_reference_duration_sec': config.vision_reference_duration_sec,
        'frame_context_max_entries': config.frame_context_max_entries,
        'scene_aware_frames': config.scene_aware_frames,
        'frame_select_budget': config.frame_select_budget,
        'gemini_synth_max_images': config.gemini_synth_max_images,
        'scene_detect_threshold': config.scene_detect_threshold,
        'min_segment_duration': config.min_segment_duration,
        'segment_fallback_window_sec': config.segment_fallback_window_sec,
        'enable_fal': config.enable_fal,
        'fal_detailed_analysis': config.fal_detailed_analysis,
        'enable_nova': config.enable_nova,
        'nova_model_id': config.nova_model_id,
        'nova_video_s3_uri': config.nova_video_s3_uri or None,
        'nova_input_usd_per_1m': config.nova_input_usd_per_1m,
        'nova_output_usd_per_1m': config.nova_output_usd_per_1m,
        'ollama_host': config.ollama_host,
        'fal_video_url': config.fal_video_url or None,
    }
