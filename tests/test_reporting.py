"""Tests for results export."""

import json
from pathlib import Path

import pandas as pd

from video_benchmark.config import BenchmarkConfig, config_manifest_dict
from video_benchmark.reporting import _frame_count_from_row, format_three_way_report


def _sample_config(**overrides) -> BenchmarkConfig:
    base = dict(
        gemini_model='gemini-2.5-flash',
        oss_backend='llama_cpp',
        oss_vision_repo_id='unsloth/Qwen2.5-VL-3B-Instruct-GGUF',
        oss_vision_repo_filename='Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf',
        oss_vision_mmproj_repo_filename='mmproj-F16.gguf',
        oss_vision_chat_format='qwen2.5-vl',
        oss_synth_repo_id='Qwen/Qwen2.5-7B-Instruct-GGUF',
        oss_synth_repo_filename='qwen2.5-7b-instruct-q3_k_m.gguf',
        oss_synth_max_tokens=2048,
        oss_frame_context_max_entries=16,
        oss_frame_insight_max_chars=240,
        oss_vision_model='llava:13b',
        ollama_host=None,
        whisper_model='small',
        whisperx_model='small.en',
        whisperx_diarization_model='pyannote/speaker-diarization-3.1',
        whisperx_min_speakers=2,
        whisperx_num_speakers=None,
        oss_asr='whisperx',
        audio_split_mode='full',
        audio_chunk_duration_sec=10.0,
        audio_chunk_max_bytes=24 * 1024 * 1024,
        gemini_vision_mode='per_frame',
        gemini_vision_batch_size=6,
        max_vision_keyframes=12,
        vision_sample_keyframes=24,
        vision_reference_duration_sec=260.0,
        frame_context_max_entries=16,
        scene_aware_frames=True,
        frame_select_budget=16,
        gemini_synth_max_images=8,
        scene_detect_threshold=20.0,
        min_segment_duration=1.0,
        segment_fallback_window_sec=10.0,
        enable_fal=False,
        fal_video_url='',
        fal_detailed_analysis=False,
        enable_nova=False,
        nova_model_id='amazon.nova-pro-v1:0',
        nova_video_s3_uri='',
        nova_input_usd_per_1m=-1.0,
        nova_output_usd_per_1m=-1.0,
        benchmark_reset=False,
        benchmark_tune_tag='test',
    )
    base.update(overrides)
    return BenchmarkConfig(**base)


def test_format_three_way_report_contains_paths():
    row = pd.Series(
        {
            'query': 'Test?',
            'native_insight': 'native',
            'gemini_orchestrated_insight': 'gemini',
            'oss_insight': 'oss',
            'native_cost': 0.1,
            'gemini_orchestrated_total': 0.05,
            'oss_cost': 0.0,
            'cost_delta_native_vs_gemini': 0.05,
            'keyframe_count': 24,
            'gemini_synthesis_frame_count': 16,
        }
    )
    report = format_three_way_report(row, _sample_config())
    assert 'PATH 1' in report
    assert 'PATH 2' in report
    assert 'PATH 3' in report
    assert 'llama_cpp' in report
    assert 'WhisperX' in report
    assert '24 API frames' in report
    assert '16 frames in context' in report


def test_format_report_hides_path3_when_not_selected():
    row = pd.Series(
        {
            'query': 'Test?',
            'native_insight': 'native',
            'gemini_orchestrated_insight': 'gemini',
            'oss_insight': 'oss leftover',
            'native_cost': 0.1,
            'gemini_orchestrated_total': 0.05,
            'oss_cost': 0.0,
        }
    )
    report = format_three_way_report(row, _sample_config(), paths={'1', '2'})
    assert 'PATH 1' in report
    assert 'PATH 2' in report
    assert 'PATH 3' not in report
    assert 'oss leftover' not in report


def test_format_report_includes_fal_and_nova_when_enabled():
    row = pd.Series(
        {
            'query': 'Test?',
            'native_insight': 'native',
            'gemini_orchestrated_insight': 'gemini',
            'oss_insight': 'oss',
            'fal_insight': 'fal says hi',
            'nova_insight': 'nova says hi',
            'native_cost': 0.1,
            'gemini_orchestrated_total': 0.05,
            'oss_cost': 0.0,
            'fal_cost': 0.51,
            'nova_cost': 0.02,
            'cost_delta_native_vs_gemini': 0.05,
            'cost_delta_native_vs_fal': -0.41,
            'cost_delta_native_vs_nova': 0.08,
        }
    )
    report = format_three_way_report(
        row, _sample_config(enable_fal=True, enable_nova=True)
    )
    assert 'PATH 4' in report
    assert 'PATH 5' in report
    assert 'fal says hi' in report
    assert 'nova says hi' in report
    assert 'fal_cost' in report
    assert 'nova_cost' in report
    assert 'capped at 120s' in report
    assert 'amazon.nova-pro-v1:0' in report


def test_config_manifest_serializable():
    manifest = config_manifest_dict(_sample_config())
    assert manifest['oss_synth_repo_id'] == 'Qwen/Qwen2.5-7B-Instruct-GGUF'
    assert 'vision_reference_duration_sec' in manifest
    assert 'enable_fal' in manifest
    assert 'nova_model_id' in manifest
    json.dumps(manifest)


def test_frame_count_from_row_uses_frame_context_list():
    row = pd.Series(
        {
            'gemini_frame_context': [
                {'pos_msec': 0.0, 'frame_insight': 'a'},
                {'pos_msec': 1000.0, 'frame_insight': 'b'},
            ],
            'gemini_vision_rollup': {'frame_count': 0},
        }
    )
    assert _frame_count_from_row(row) == 2


def test_export_run_without_keyframes(tmp_path: Path, monkeypatch):
    from video_benchmark import pipeline
    from video_benchmark.reporting import export_run

    class _Tail:
        def __init__(self, df):
            self._df = df

        def to_pandas(self):
            return self._df

    class _Select:
        def __init__(self, df):
            self._df = df

        def tail(self, _n):
            return _Tail(self._df)

        def collect(self):
            return self

        def to_pandas(self):
            return self._df

    class FakeVS:
        def columns(self):
            return ['query', 'video_duration_sec', 'native_insight', 'native_cost']

        def __getattr__(self, name):
            return name

        def select(self, *cols):
            return _Select(
                pd.DataFrame(
                    [
                        {
                            'query': 'Q',
                            'video_duration_sec': 10.0,
                            'native_insight': 'native only',
                            'native_cost': 0.1,
                        }
                    ]
                )
            )

    monkeypatch.setattr(pipeline, 'video_sources', FakeVS())
    monkeypatch.setattr(pipeline, 'keyframes', None)
    monkeypatch.setattr(pipeline, 'audio_chunks', None)
    out = export_run(_sample_config(), tmp_path, '/tmp/v.mp4', 'Q', paths={'1'})
    assert (out / 'REPORT.md').exists()
    assert (out / 'summary.json').exists()
    assert not (out / 'keyframes.csv').exists()
    assert 'PATH 1' in (out / 'REPORT.md').read_text()
    assert 'PATH 3' not in (out / 'REPORT.md').read_text()
    summary = json.loads((out / 'summary.json').read_text())
    assert summary['native_cost'] == 0.1
    assert 'oss_cost' not in summary
    assert 'gemini_orchestrated_total' not in summary


def test_export_run_coerces_nan_costs(tmp_path: Path, monkeypatch):
    from video_benchmark import pipeline
    from video_benchmark.reporting import export_run

    class _Tail:
        def __init__(self, df):
            self._df = df

        def to_pandas(self):
            return self._df

    class _Select:
        def __init__(self, df):
            self._df = df

        def tail(self, _n):
            return _Tail(self._df)

        def collect(self):
            return self

        def to_pandas(self):
            return self._df

    class FakeVS:
        def columns(self):
            return ['query', 'video_duration_sec', 'native_insight', 'native_cost']

        def __getattr__(self, name):
            return name

        def select(self, *cols):
            return _Select(
                pd.DataFrame(
                    [
                        {
                            'query': 'Q',
                            'video_duration_sec': 10.0,
                            'native_insight': 'native only',
                            'native_cost': float('nan'),
                        }
                    ]
                )
            )

    monkeypatch.setattr(pipeline, 'video_sources', FakeVS())
    monkeypatch.setattr(pipeline, 'keyframes', None)
    monkeypatch.setattr(pipeline, 'audio_chunks', None)
    out = export_run(_sample_config(), tmp_path, '/tmp/v.mp4', 'Q', paths={'1'})
    summary = json.loads((out / 'summary.json').read_text())
    assert summary['native_cost'] == 0.0
