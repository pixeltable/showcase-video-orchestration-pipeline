"""Insert video, recompute context columns, and resolve sample paths."""

from __future__ import annotations

import os
import sys
import urllib.request
from pathlib import Path

import pixeltable as pxt

from video_benchmark import pipeline
from video_benchmark.config import ASSETS_DIR, DEFAULT_SAMPLE, PURSUIT_VIDEO_URL, BenchmarkConfig
from video_benchmark.paths import DEFAULT_PATHS
from video_benchmark.schema import CATALOG_DIR


def ensure_sample_video(video_path: Path | None = None) -> str:
    if video_path is not None:
        path = video_path.expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f'Video not found: {path}')
        return str(path)

    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    if not DEFAULT_SAMPLE.exists():
        print(f'Downloading sample video to {DEFAULT_SAMPLE} ...')
        urllib.request.urlretrieve(PURSUIT_VIDEO_URL, DEFAULT_SAMPLE)
    return str(DEFAULT_SAMPLE.resolve())


def _warn_list_context(vs: pxt.Table, column: str, label: str) -> None:
    if not _has_column(vs, column):
        return
    rows = vs.select(getattr(vs, column)).tail(1).to_pandas()
    if rows.empty:
        return
    ctx = rows.iloc[0][column]
    count = len(ctx) if isinstance(ctx, list) else 0
    if count == 0:
        print(f'Warning: {label} is empty before synthesis recompute.', file=sys.stderr)


def _has_column(vs: pxt.Table, column: str) -> bool:
    try:
        return column in vs.columns()
    except Exception:
        return hasattr(vs, column)


def _recompute_column(vs: pxt.Table, column: str, *, cascade: bool = False) -> None:
    if not _has_column(vs, column):
        print(f'Skip recompute ({column}): column not in catalog.', file=sys.stderr)
        return
    status = vs.recompute_columns(column, cascade=cascade)
    if status.num_excs:
        print(f'Recompute ({column}): {status.insert_msg()}', file=sys.stderr)


def run_benchmark(
    config: BenchmarkConfig,
    video_path: str,
    query: str,
    paths: set[str] | None = None,
) -> None:
    if pipeline.video_sources is None:
        raise RuntimeError('Pipeline not initialized')

    active = set(paths) if paths is not None else set(DEFAULT_PATHS)
    vs = pipeline.video_sources
    print(f'Inserting video: {video_path}')
    print(f'Query: {query}')
    print(f'Paths: {",".join(sorted(active))}')
    print(f'Gemini model (paths 1+2): {config.gemini_model}')
    if '3' in active:
        print(
            f'OSS backend: {config.oss_backend} | '
            f'vision={config.oss_vision_repo_id} | '
            f'synth={config.oss_synth_repo_id}'
        )
    print(
        f'Native extras: fal={"on" if ("4" in active and config.enable_fal) else "off"} | '
        f'nova={"on" if ("5" in active and config.enable_nova) else "off"}'
        + (f' ({config.nova_model_id})' if ('5' in active and config.enable_nova) else '')
    )
    print(
        f'Segmentation: scene_cuts → segment_times '
        f'(fallback {config.segment_fallback_window_sec}s windows) | '
        f'Audio split: {config.audio_split_mode} | OSS ASR: {config.oss_asr} | '
        f'Vision: {config.gemini_vision_mode} '
        f'(sample_kf={config.vision_sample_keyframes}, cap={config.frame_context_max_entries}, '
        f'scene_aware={config.scene_aware_frames}, synth_images={config.gemini_synth_max_images})'
    )
    if config.benchmark_tune_tag:
        print(f'Tune tag: {config.benchmark_tune_tag}')
    requested_asr = os.environ.get('OSS_ASR', 'whisperx').strip().lower()
    if '3' in active and requested_asr == 'whisperx' and config.oss_asr == 'whisper':
        print(
            'Note: OSS_ASR=whisperx requested but HF_TOKEN is missing; '
            'using whisper with timestamped segments (no speaker diarization).',
            file=sys.stderr,
        )
    if '3' in active and not _has_column(vs, 'oss_insight'):
        print(
            'Soft-skip Path 3: OSS columns missing (use --reset with --paths including 3, '
            'and install .[oss] + llama-cpp-python).',
            file=sys.stderr,
        )
        active.discard('3')

    status = vs.insert([{'video': video_path, 'query': query}], return_rows=True)
    if status.num_excs:
        print(f'Insert: {status.insert_msg()}', file=sys.stderr)
        if status.cols_with_excs:
            print(f'Columns with errors: {", ".join(status.cols_with_excs)}', file=sys.stderr)

    if '2' in active:
        # Path 2: transcripts → frames → summarize → synthesis
        _recompute_column(vs, 'gemini_transcript_context')
        _warn_list_context(vs, 'gemini_transcript_context', 'gemini_transcript_context')
        _recompute_column(vs, 'gemini_asr_cost')
        # Batched vision is the paid multi-image UDF; insert already ran it.
        if config.gemini_vision_mode != 'batched':
            _recompute_column(vs, 'gemini_frame_context')
        _recompute_column(vs, 'gemini_vision_rollup')
        _recompute_column(vs, 'gemini_vision_track_cost')
        _recompute_column(vs, 'gemini_frame_context_deduped')
        if config.scene_aware_frames:
            _recompute_column(vs, 'gemini_frame_context_selected')
        _recompute_column(vs, 'gemini_frame_context_summarized')
        _warn_list_context(vs, 'gemini_frame_context_summarized', 'gemini_frame_context_summarized')
        _recompute_column(vs, 'gemini_orchestrated_context', cascade=True)
        _recompute_column(vs, 'gemini_synthesis_prompt_text')
        _recompute_column(vs, 'gemini_synthesis_contents')
        _recompute_column(vs, 'gemini_orchestrated_insight')
        _recompute_column(vs, 'gemini_synthesis_cost')
        _recompute_column(vs, 'gemini_orchestrated_total')
        if '1' in active:
            _recompute_column(vs, 'cost_delta_native_vs_gemini')

    if '3' in active:
        # Path 3: transcripts → frames → dedupe → summarize → compact → synthesis
        _recompute_column(vs, 'oss_transcript_context')
        _warn_list_context(vs, 'oss_transcript_context', 'oss_transcript_context')
        _recompute_column(vs, 'oss_frame_context')
        _recompute_column(vs, 'oss_frame_context_deduped')
        _warn_list_context(vs, 'oss_frame_context_deduped', 'oss_frame_context_deduped')
        if config.scene_aware_frames:
            _recompute_column(vs, 'oss_frame_context_selected')
        _recompute_column(vs, 'oss_frame_context_summarized')
        _warn_list_context(vs, 'oss_frame_context_summarized', 'oss_frame_context_summarized')
        _recompute_column(vs, 'oss_frame_context_compact')
        _warn_list_context(vs, 'oss_frame_context_compact', 'oss_frame_context_compact')
        _recompute_column(vs, 'oss_context')
        _recompute_column(vs, 'oss_synthesis_prompt_text')
        _recompute_column(vs, 'oss_insight')

    # Paths 4/5 run on insert; recomputing fal_video_url would re-upload without
    # re-running fal_response.
    if '4' in active and not config.enable_fal:
        print(
            'Soft-skip Path 4: set ENABLE_FAL=1 and FAL_KEY (pip install -e ".[fal]").',
            file=sys.stderr,
        )
    elif '4' in active and not _has_column(vs, 'fal_insight'):
        print(
            'Soft-skip Path 4: fal columns missing (use --reset with --paths including 4).',
            file=sys.stderr,
        )

    if '5' in active and not config.enable_nova:
        print(
            'Soft-skip Path 5: set ENABLE_NOVA=1 and AWS/Bedrock creds '
            '(pip install -e ".[bedrock]").',
            file=sys.stderr,
        )
    elif '5' in active and not _has_column(vs, 'nova_insight'):
        print(
            'Soft-skip Path 5: nova columns missing (use --reset with --paths including 5).',
            file=sys.stderr,
        )


def reset_catalog() -> None:
    print(f'Resetting {CATALOG_DIR} catalog ...')
    pxt.drop_dir(CATALOG_DIR, force=True, if_not_exists='ignore')
    pipeline.clear_handles()
