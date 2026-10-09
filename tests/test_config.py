"""Config defaults and validation."""

from __future__ import annotations

import os

import pytest

from video_benchmark.config import config_manifest_dict, load_config

KNOBS = (
    'GEMINI_MODEL',
    'VISION_SAMPLE_KEYFRAMES',
    'FRAME_SELECT_BUDGET',
    'GEMINI_SYNTH_MAX_IMAGES',
    'OSS_SYNTH_MAX_TOKENS',
    'OSS_FRAME_CAPTION_MAX_CHARS',
    'OSS_ASR',
    'HF_TOKEN',
    'HUGGING_FACE_HUB_TOKEN',
    'ENABLE_FAL',
    'ENABLE_NOVA',
    'FAL_KEY',
    'FAL_API_KEY',
    'AWS_ACCESS_KEY_ID',
    'AWS_SECRET_ACCESS_KEY',
    'BEDROCK_API_KEY',
    'NOVA_MODEL_ID',
    'AWS_PROFILE',
    'AWS_DEFAULT_PROFILE',
    'AWS_BEARER_TOKEN_BEDROCK',
    'SCENE_DETECT_THRESHOLD', 'WHISPERX_NUM_SPEAKERS', 'WHISPERX_MIN_SPEAKERS',
    'VIDEOME_VISION_SAMPLE_KEYFRAMES', 'VIDEOME_FRAME_SELECT_BUDGET',
)


@pytest.fixture
def clean_env(monkeypatch):
    for key in KNOBS:
        # setenv first so teardown restores the key even if load_config() writes it.
        monkeypatch.setenv(key, '')
        monkeypatch.delenv(key)
    # Keep the project .env (with real keys) out of the test process.
    monkeypatch.setattr('video_benchmark.config.load_dotenv', lambda env_path=None: None)
    return monkeypatch


def test_defaults(clean_env):
    cfg = load_config()
    assert cfg.gemini_model == 'gemini-2.5-flash'
    assert (cfg.vision_sample_keyframes, cfg.frame_select_budget) == (24, 16)
    assert cfg.gemini_synth_max_images == 8
    assert cfg.oss_synth_repo_id == 'Qwen/Qwen2.5-7B-Instruct-GGUF'
    assert cfg.nova_model_id == 'amazon.nova-pro-v1:0'
    assert cfg.enable_fal is False
    assert cfg.enable_nova is False
    # WhisperX diarization needs a Hugging Face token; without one Path 3 uses Whisper.
    assert cfg.oss_asr == 'whisper'


def test_whisperx_kept_with_hf_token(clean_env):
    clean_env.setenv('HF_TOKEN', 'hf_test')
    assert load_config().oss_asr == 'whisperx'


def test_fal_key_aliases(clean_env):
    clean_env.setenv('FAL_API_KEY', 'fal_test')
    cfg = load_config()
    assert cfg.enable_fal is True
    assert os.environ['FAL_KEY'] == 'fal_test'


def test_unknown_values_are_rejected(clean_env):
    clean_env.setenv('OSS_ASR', 'foo')
    with pytest.raises(ValueError, match='OSS_ASR'):
        load_config()
    clean_env.delenv('OSS_ASR')
    clean_env.setenv('GEMINI_MODEL', 'gemini-9-ultra')
    with pytest.raises(ValueError, match='no price'):
        load_config()
    clean_env.setenv('GEMINI_MODEL', 'gemini-2.5-flash')
    clean_env.setenv('FRAME_SELECT_BUDGET', '0')
    with pytest.raises(ValueError, match='at least 1'):
        load_config()


def test_manifest_is_the_whole_config(clean_env):
    cfg = load_config()
    manifest = config_manifest_dict(cfg)
    assert manifest['gemini_model'] == cfg.gemini_model
    assert manifest['benchmark_tune_tag'] is None
    assert set(manifest) >= {'vision_sample_keyframes', 'frame_select_budget', 'oss_asr'}


@pytest.mark.parametrize(('name', 'value'), [
    ('GEMINI_SYNTH_MAX_IMAGES', '-1'), ('OSS_SYNTH_MAX_TOKENS', '0'),
    ('OSS_FRAME_CAPTION_MAX_CHARS', '0'), ('SCENE_DETECT_THRESHOLD', 'nan'),
    ('SCENE_DETECT_THRESHOLD', '-1'), ('WHISPERX_NUM_SPEAKERS', '0'),
    ('WHISPERX_MIN_SPEAKERS', '0'),
])
def test_invalid_numeric_knobs_are_rejected_before_catalog_changes(clean_env, name, value):
    clean_env.setenv(name, value)
    with pytest.raises(ValueError, match=name):
        load_config()


def test_nova_supports_profile_credentials_and_rejects_unpriced_models(clean_env):
    clean_env.setenv('AWS_PROFILE', 'developer-sso')
    assert load_config().enable_nova
    clean_env.setenv('NOVA_MODEL_ID', 'amazon.future-model')
    with pytest.raises(ValueError, match='NOVA_MODEL_ID'):
        load_config()


def test_native_ignores_all_inactive_media_and_provider_knobs(clean_env):
    for name in ('VISION_SAMPLE_KEYFRAMES', 'FRAME_SELECT_BUDGET', 'GEMINI_SYNTH_MAX_IMAGES',
                 'SCENE_DETECT_THRESHOLD', 'OSS_ASR', 'OSS_SYNTH_MAX_TOKENS',
                 'WHISPERX_MIN_SPEAKERS', 'WHISPERX_NUM_SPEAKERS', 'NOVA_MODEL_ID'):
        clean_env.setenv(name, 'invalid')
    clean_env.setenv('AWS_PROFILE', 'incidental-profile')
    cfg = load_config({'1'})
    assert cfg.vision_sample_keyframes == 24 and not cfg.enable_nova
    clean_env.setenv('HF_TOKEN', 'incidental-token')
    assert load_config({'1'}) == cfg  # inactive settings also keep the frozen definition stable


def test_nova_only_ignores_gemini_and_local_settings(clean_env):
    clean_env.setenv('AWS_PROFILE', 'profile')
    for name in ('GEMINI_MODEL', 'OSS_ASR', 'VISION_SAMPLE_KEYFRAMES'):
        clean_env.setenv(name, 'invalid')
    assert load_config({'5'}).enable_nova


def test_nova_without_credentials_cannot_gate_a_native_run(clean_env):
    clean_env.setenv('NOVA_MODEL_ID', 'unpriced-unused')
    cfg = load_config({'1', '5'})
    assert not cfg.enable_nova and cfg.nova_model_id == 'amazon.nova-pro-v1:0'


@pytest.mark.parametrize('asr', ['whisper', 'whisperx', 'gemini'])
def test_local_gemini_price_validation_matches_effective_asr(clean_env, asr):
    clean_env.setenv('OSS_ASR', asr)
    clean_env.setenv('HF_TOKEN', 'fixture')
    clean_env.setenv('GEMINI_MODEL', 'unpriced')
    if asr == 'gemini':
        with pytest.raises(ValueError, match='no price'):
            load_config({'3'})
    else:
        assert load_config({'3'}).oss_asr == asr


def test_videomme_validates_forced_gemini_asr_and_effective_frame_settings(clean_env):
    clean_env.setenv('OSS_ASR', 'invalid-but-overridden')
    clean_env.setenv('GEMINI_MODEL', 'unpriced')
    with pytest.raises(ValueError, match='no price'):
        load_config({'3'}, videomme=True)
    clean_env.setenv('GEMINI_MODEL', 'gemini-2.5-flash')
    clean_env.setenv('VISION_SAMPLE_KEYFRAMES', 'invalid-but-overridden')
    assert load_config({'3'}, videomme=True).vision_sample_keyframes == 32
    clean_env.setenv('VIDEOME_FRAME_SELECT_BUDGET', '0')
    with pytest.raises(ValueError, match='at least 1'):
        load_config({'2'}, videomme=True)
    assert load_config({'1'}, videomme=True).frame_select_budget == 24
