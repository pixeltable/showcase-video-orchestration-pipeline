"""Config default and env-fallback tests."""

from __future__ import annotations

from video_benchmark.config import config_manifest_dict, load_config


def test_load_config_defaults_match_canonical(monkeypatch):
    # Clear knobs that would override code defaults.
    for key in (
        'SCENE_AWARE_FRAMES',
        'OSS_SYNTH_REPO_ID',
        'OSS_SYNTH_REPO_FILENAME',
        'OSS_SYNTH_MAX_TOKENS',
        'OSS_FRAME_CONTEXT_MAX_ENTRIES',
        'OSS_FRAME_INSIGHT_MAX_CHARS',
        'FRAME_CONTEXT_MAX_ENTRIES',
        'VISION_SAMPLE_KEYFRAMES',
        'FRAME_SELECT_BUDGET',
        'GEMINI_SYNTH_MAX_IMAGES',
        'ENABLE_FAL',
        'ENABLE_NOVA',
        'FAL_KEY',
        'FAL_API_KEY',
        'AWS_ACCESS_KEY_ID',
        'AWS_SECRET_ACCESS_KEY',
        'AWS_BEARER_TOKEN_BEDROCK',
        'BEDROCK_API_KEY',
        'OSS_ASR',
        'HF_TOKEN',
        'HUGGING_FACE_HUB_TOKEN',
    ):
        monkeypatch.delenv(key, raising=False)

    # Avoid loading project .env secrets into this test process for ASR mode.
    monkeypatch.setattr('video_benchmark.config.load_dotenv', lambda env_path=None: None)

    cfg = load_config()
    assert cfg.scene_aware_frames is True
    assert cfg.vision_sample_keyframes == 24
    assert cfg.frame_context_max_entries == 16
    assert cfg.frame_select_budget == 16
    assert cfg.oss_synth_repo_id == 'Qwen/Qwen2.5-7B-Instruct-GGUF'
    assert cfg.oss_synth_repo_filename == 'qwen2.5-7b-instruct-q3_k_m.gguf'
    assert cfg.oss_synth_max_tokens == 2048
    assert cfg.oss_frame_context_max_entries == 16
    assert cfg.oss_frame_insight_max_chars == 240
    assert cfg.gemini_synth_max_images == 8
    assert cfg.enable_fal is False
    assert cfg.enable_nova is False
    # Without HF token, whisperx falls back to whisper.
    assert cfg.oss_asr == 'whisper'


def test_whisperx_kept_when_hf_token_present(monkeypatch):
    monkeypatch.setattr('video_benchmark.config.load_dotenv', lambda env_path=None: None)
    monkeypatch.setenv('HF_TOKEN', 'hf_test_token')
    monkeypatch.setenv('OSS_ASR', 'whisperx')
    cfg = load_config()
    assert cfg.oss_asr == 'whisperx'


def test_config_manifest_includes_vision_reference_duration(monkeypatch):
    monkeypatch.setattr('video_benchmark.config.load_dotenv', lambda env_path=None: None)
    monkeypatch.setenv('HF_TOKEN', 'hf_test_token')
    cfg = load_config()
    manifest = config_manifest_dict(cfg)
    assert 'vision_reference_duration_sec' in manifest
    assert manifest['vision_reference_duration_sec'] == cfg.vision_reference_duration_sec
