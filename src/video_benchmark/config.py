"""Environment configuration for the benchmark paths."""

from __future__ import annotations

import math
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from video_benchmark.pricing import GEMINI_RATES, nova_model_rates

DEFAULT_QUERY = 'Summarize the main activities, speakers, and visual events in this video.'
PURSUIT_VIDEO_URL = (
    'https://raw.githubusercontent.com/pixeltable/pixeltable/main/docs/resources/'
    'The-Pursuit-of-Happiness.mp4'
)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
ASSETS_DIR = PROJECT_ROOT / 'assets'
DEFAULT_SAMPLE = ASSETS_DIR / 'pursuit-of-happiness.mp4'

# One chunk per file: Gemini transcribes a whole video's audio in a single call.
AUDIO_SPLIT_FULL_DURATION_SEC = 1_000_000.0

OSS_ASR_CHOICES = ('whisper', 'whisperx', 'gemini')


@dataclass(frozen=True)
class BenchmarkConfig:
    gemini_model: str
    vision_sample_keyframes: int
    frame_select_budget: int
    gemini_synth_max_images: int
    scene_detect_threshold: float
    oss_vision_repo_id: str
    oss_vision_repo_filename: str
    oss_vision_mmproj_repo_filename: str
    oss_vision_chat_format: str
    oss_synth_repo_id: str
    oss_synth_repo_filename: str
    oss_synth_max_tokens: int
    oss_frame_caption_max_chars: int
    oss_asr: str
    whisper_model: str
    whisperx_model: str
    whisperx_diarization_model: str
    whisperx_min_speakers: int
    whisperx_num_speakers: int | None
    enable_fal: bool
    enable_nova: bool
    nova_model_id: str
    benchmark_tune_tag: str
    default_query: str = DEFAULT_QUERY

    def __post_init__(self) -> None:
        for name in (
            'vision_sample_keyframes', 'frame_select_budget', 'oss_synth_max_tokens',
            'oss_frame_caption_max_chars', 'whisperx_min_speakers',
        ):
            if getattr(self, name) < 1:
                raise ValueError(f'{name.upper()} must be at least 1')
        if self.gemini_synth_max_images < 0:
            raise ValueError('GEMINI_SYNTH_MAX_IMAGES must be zero or greater')
        if not math.isfinite(self.scene_detect_threshold) or self.scene_detect_threshold <= 0:
            raise ValueError('SCENE_DETECT_THRESHOLD must be finite and greater than zero')
        if self.whisperx_num_speakers is not None and self.whisperx_num_speakers < 1:
            raise ValueError('WHISPERX_NUM_SPEAKERS must be at least 1')
        if self.enable_nova:
            nova_model_rates(self.nova_model_id)


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
    return int(raw) if raw else None


def _env_bool(name: str) -> bool:
    return os.environ.get(name, '').strip().lower() in {'1', 'true', 'yes'}


def _fal_enabled() -> bool:
    if os.environ.get('ENABLE_FAL') is not None:
        return _env_bool('ENABLE_FAL')
    return bool(os.environ.get('FAL_KEY'))


def _nova_enabled() -> bool:
    if os.environ.get('ENABLE_NOVA') is not None:
        return _env_bool('ENABLE_NOVA')
    if any(os.environ.get(key) for key in (
        'BEDROCK_API_KEY', 'AWS_BEARER_TOKEN_BEDROCK', 'AWS_PROFILE', 'AWS_DEFAULT_PROFILE',
    )):
        return True
    return bool(os.environ.get('AWS_ACCESS_KEY_ID') and os.environ.get('AWS_SECRET_ACCESS_KEY'))


def load_config(paths: set[str] | None = None, *, videomme: bool = False) -> BenchmarkConfig:
    """Load effective settings for selected paths; omitted paths retain full validation.

    Inactive fields take stable defaults instead of reading unrelated environment knobs.
    Video-MME uses Gemini ASR for Path 3, and its own frame/model defaults.
    """
    load_dotenv()
    active = paths if paths is not None else {'1', '1L', '2', '3', '4', '5'}
    modular = bool(active & {'2', '3'})

    def setting(name: str, default: str, used: bool = True) -> str:
        return os.environ.get(name, default) if used else default

    # fal_client.upload_file reads FAL_KEY; Pixeltable's fal client reads FAL_API_KEY.
    if os.environ.get('FAL_API_KEY') and not os.environ.get('FAL_KEY'):
        os.environ['FAL_KEY'] = os.environ['FAL_API_KEY']
    if os.environ.get('FAL_KEY') and not os.environ.get('FAL_API_KEY'):
        os.environ['FAL_API_KEY'] = os.environ['FAL_KEY']
    # Pixeltable's Bedrock client uses the boto3 region chain; Nova video runs in us-east-1.
    os.environ.setdefault('AWS_DEFAULT_REGION', 'us-east-1')
    nova_enabled = '5' in active and _nova_enabled()

    oss_default = 'whisperx' if '3' in active else 'whisper'
    oss_asr = ('gemini' if videomme else setting('OSS_ASR', oss_default, '3' in active)).lower()
    oss_asr = oss_asr.strip()
    if oss_asr not in OSS_ASR_CHOICES:
        raise ValueError(f'OSS_ASR must be one of {", ".join(OSS_ASR_CHOICES)} (got {oss_asr!r})')
    # pyannote diarization needs a Hugging Face token; without one, use Whisper.
    if oss_asr == 'whisperx' and not (
        os.environ.get('HF_TOKEN') or os.environ.get('HUGGING_FACE_HUB_TOKEN')
    ):
        oss_asr = 'whisper'
    gemini_used = bool(active & {'1', '1L', '2'}) or ('3' in active and oss_asr == 'gemini')
    gemini_model = setting('GEMINI_MODEL', 'gemini-2.5-flash', gemini_used).strip()
    if gemini_used and gemini_model not in GEMINI_RATES:
        raise ValueError(
            f'GEMINI_MODEL={gemini_model!r} has no price in pricing.GEMINI_RATES '
            f'(priced: {", ".join(sorted(GEMINI_RATES))}). Add its rates before running.'
        )
    frame_prefix = 'VIDEOME_' if videomme else ''
    sample = int(setting(f'{frame_prefix}VISION_SAMPLE_KEYFRAMES', '32' if videomme else '24',
                         modular))
    budget = int(setting(f'{frame_prefix}FRAME_SELECT_BUDGET', '24' if videomme else '16', modular))
    if sample < 1 or budget < 1:
        raise ValueError('VISION_SAMPLE_KEYFRAMES and FRAME_SELECT_BUDGET must be at least 1')

    return BenchmarkConfig(
        gemini_model=gemini_model,
        vision_sample_keyframes=sample,
        frame_select_budget=budget,
        gemini_synth_max_images=int(setting('GEMINI_SYNTH_MAX_IMAGES', '8', '2' in active)),
        scene_detect_threshold=float(setting('SCENE_DETECT_THRESHOLD', '20.0', modular)),
        oss_vision_repo_id=setting(
            'OSS_VISION_REPO_ID', 'unsloth/Qwen2.5-VL-3B-Instruct-GGUF', '3' in active
        ),
        oss_vision_repo_filename=setting(
            'OSS_VISION_REPO_FILENAME', 'Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf', '3' in active
        ),
        oss_vision_mmproj_repo_filename=setting(
            'OSS_VISION_MMPROJ_REPO_FILENAME', 'mmproj-F16.gguf', '3' in active
        ),
        oss_vision_chat_format=setting(
            'OSS_VISION_CHAT_FORMAT', 'qwen2.5-vl', '3' in active
        ).strip(),
        oss_synth_repo_id=setting(
            'OSS_SYNTH_REPO_ID', 'Qwen/Qwen2.5-7B-Instruct-GGUF', '3' in active
        ),
        oss_synth_repo_filename=setting(
            'OSS_SYNTH_REPO_FILENAME', 'qwen2.5-7b-instruct-q3_k_m.gguf', '3' in active
        ),
        oss_synth_max_tokens=int(setting('OSS_SYNTH_MAX_TOKENS', '2048', '3' in active)),
        oss_frame_caption_max_chars=int(setting(
            'OSS_FRAME_CAPTION_MAX_CHARS', '240', '3' in active
        )),
        oss_asr=oss_asr,
        whisper_model=setting('WHISPER_MODEL', 'small', '3' in active and oss_asr == 'whisper'),
        whisperx_model=setting(
            'WHISPERX_MODEL', 'small.en', '3' in active and oss_asr == 'whisperx'
        ),
        whisperx_diarization_model=setting(
            'WHISPERX_DIARIZATION_MODEL', 'pyannote/speaker-diarization-3.1',
            '3' in active and oss_asr == 'whisperx'
        ),
        whisperx_min_speakers=(
            int(setting('WHISPERX_MIN_SPEAKERS', '2',
                        paths is None or ('3' in active and oss_asr == 'whisperx')))
        ),
        whisperx_num_speakers=(
            _optional_int('WHISPERX_NUM_SPEAKERS')
            if paths is None or ('3' in active and oss_asr == 'whisperx') else None
        ),
        enable_fal='4' in active and _fal_enabled(),
        enable_nova=nova_enabled,
        nova_model_id=setting('NOVA_MODEL_ID',
                              'amazon.nova-lite-v1:0' if videomme else 'amazon.nova-pro-v1:0',
                              nova_enabled).strip(),
        benchmark_tune_tag=os.environ.get('BENCHMARK_TUNE_TAG', '').strip(),
    )


def config_manifest_dict(config: BenchmarkConfig) -> dict:
    """Serializable config for results/manifest.json (no secrets)."""
    manifest = asdict(config)
    manifest['benchmark_tune_tag'] = config.benchmark_tune_tag or None
    return manifest
