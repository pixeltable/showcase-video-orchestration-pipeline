"""Comparison output and reproducible results export."""

from __future__ import annotations

import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from video_benchmark import pipeline
from video_benchmark.config import PROJECT_ROOT, BenchmarkConfig, config_manifest_dict


def _frame_count_from_row(row: pd.Series) -> int:
    frame_context = row.get('gemini_frame_context')
    if isinstance(frame_context, list):
        return len(frame_context)
    rollup = row.get('gemini_vision_rollup')
    if isinstance(rollup, dict):
        return int(rollup.get('frame_count', 0) or 0)
    return 0


def _audio_chunk_count_from_row(row: pd.Series) -> int:
    if pipeline.audio_chunks is not None:
        try:
            return int(pipeline.audio_chunks.count())
        except Exception:
            pass
    transcript_context = row.get('gemini_transcript_context')
    if isinstance(transcript_context, list):
        return len(transcript_context)
    return 0


def _synthesis_frame_count_from_row(row: pd.Series) -> int:
    summarized = row.get('gemini_frame_context_summarized')
    if isinstance(summarized, list):
        return len(summarized)
    return 0


def _optional_col(name: str):
    if pipeline.video_sources is None:
        return None
    return getattr(pipeline.video_sources, name, None)


def _latest_video_row() -> pd.Series | None:
    if pipeline.video_sources is None:
        raise RuntimeError('Pipeline not initialized')
    required = ['query', 'video_duration_sec']
    optional = [
        'native_insight',
        'gemini_orchestrated_insight',
        'oss_insight',
        'native_cost',
        'gemini_orchestrated_total',
        'gemini_vision_track_cost',
        'gemini_asr_cost',
        'gemini_synthesis_cost',
        'oss_cost',
        'cost_delta_native_vs_gemini',
        'gemini_frame_context',
        'gemini_frame_context_summarized',
        'gemini_transcript_context',
        'gemini_vision_rollup',
        'fal_insight',
        'fal_cost',
        'cost_delta_native_vs_fal',
        'nova_insight',
        'nova_cost',
        'cost_delta_native_vs_nova',
    ]
    cols = []
    for name in required:
        cols.append(getattr(pipeline.video_sources, name))
    for name in optional:
        col = _optional_col(name)
        if col is not None:
            cols.append(col)
    rows = pipeline.video_sources.select(*cols).tail(1).to_pandas()
    if rows.empty:
        return None
    return rows.iloc[0]


def build_comparison_dataframe() -> pd.DataFrame:
    if pipeline.keyframes is None or pipeline.video_sources is None:
        raise RuntimeError('Pipeline not initialized')

    summary_names = [
        'query',
        'native_insight',
        'gemini_orchestrated_insight',
        'oss_insight',
        'native_cost',
        'gemini_orchestrated_total',
        'oss_cost',
        'cost_delta_native_vs_gemini',
        'gemini_frame_context',
        'gemini_vision_rollup',
        'fal_insight',
        'fal_cost',
        'nova_insight',
        'nova_cost',
    ]
    summary_cols = []
    for name in summary_names:
        if name == 'query':
            summary_cols.append(pipeline.video_sources.query)
            continue
        col = _optional_col(name)
        if col is not None:
            summary_cols.append(col)

    summary = pipeline.video_sources.select(*summary_cols).collect().to_pandas()

    video_row = summary.iloc[-1] if not summary.empty else {}

    # Per-keyframe Gemini columns exist only in per_frame mode; batched mode
    # stores insights on the parent gemini_frame_context list.
    has_per_frame_gemini = hasattr(pipeline.keyframes, 'gemini_frame_insight')
    has_oss_frame = hasattr(pipeline.keyframes, 'oss_frame_insight')
    select_kwargs: dict = {
        'frame_position': pipeline.keyframes.global_position_ms,
        'segment_start': pipeline.keyframes.segment_start,
    }
    if has_per_frame_gemini:
        select_kwargs['gemini_frame_insight'] = pipeline.keyframes.gemini_frame_insight
        select_kwargs['gemini_frame_cost'] = pipeline.keyframes.gemini_frame_cost
    if has_oss_frame:
        select_kwargs['oss_frame_insight'] = pipeline.keyframes.oss_frame_insight

    frame_df = (
        pipeline.keyframes.select(**select_kwargs)
        .order_by(pipeline.keyframes.global_position_ms)
        .collect()
        .to_pandas()
    )
    if not has_per_frame_gemini:
        frame_df['gemini_frame_insight'] = ''
        frame_df['gemini_frame_cost'] = None
        parent_frames = video_row.get('gemini_frame_context') if video_row is not None else None
        if isinstance(parent_frames, list) and not frame_df.empty:
            by_pos = {
                float(item.get('pos_msec', 0.0)): item
                for item in parent_frames
                if isinstance(item, dict)
            }
            insights = []
            costs = []
            for pos in frame_df['frame_position']:
                item = by_pos.get(float(pos), {})
                insights.append(item.get('frame_insight', ''))
                costs.append(item.get('frame_cost'))
            frame_df['gemini_frame_insight'] = insights
            frame_df['gemini_frame_cost'] = costs
    if not has_oss_frame:
        frame_df['oss_frame_insight'] = ''

    if not frame_df.empty and video_row is not None:
        frame_df['native_video_insight'] = video_row.get('native_insight', '')
        frame_df['gemini_orchestrated_insight'] = video_row.get(
            'gemini_orchestrated_insight', ''
        )
        frame_df['oss_insight'] = video_row.get('oss_insight', '')
        frame_df['fal_insight'] = video_row.get('fal_insight', '')
        frame_df['nova_insight'] = video_row.get('nova_insight', '')
        frame_df['native_cost'] = video_row.get('native_cost', 0.0)
        frame_df['gemini_orchestrated_cost'] = video_row.get('gemini_orchestrated_total', 0.0)
        frame_df['oss_cost'] = video_row.get('oss_cost', 0.0)
        frame_df['fal_cost'] = video_row.get('fal_cost', 0.0)
        frame_df['nova_cost'] = video_row.get('nova_cost', 0.0)
        frame_df['cost_delta_native_vs_gemini'] = video_row.get(
            'cost_delta_native_vs_gemini', 0.0
        )

    if not summary.empty:
        row = summary.iloc[-1]
        frame_count = _frame_count_from_row(row)
        summary_row = {
            'frame_position': 'VIDEO_TOTAL',
            'segment_start': None,
            'gemini_frame_insight': f'frames={frame_count}',
            'oss_frame_insight': '',
            'gemini_frame_cost': None,
            'native_video_insight': row.get('native_insight', ''),
            'gemini_orchestrated_insight': row.get('gemini_orchestrated_insight', ''),
            'oss_insight': row.get('oss_insight', ''),
            'fal_insight': row.get('fal_insight', ''),
            'nova_insight': row.get('nova_insight', ''),
            'native_cost': row.get('native_cost', 0.0),
            'gemini_orchestrated_cost': row.get('gemini_orchestrated_total', 0.0),
            'oss_cost': row.get('oss_cost', 0.0),
            'fal_cost': row.get('fal_cost', 0.0),
            'nova_cost': row.get('nova_cost', 0.0),
            'cost_delta_native_vs_gemini': row.get('cost_delta_native_vs_gemini', 0.0),
        }
        frame_df = pd.concat([frame_df, pd.DataFrame([summary_row])], ignore_index=True)

    return frame_df


def _oss_asr_label(oss_asr: str) -> str:
    mapping = {
        'whisperx': 'WhisperX',
        'whisper': 'Whisper',
        'gemini': 'Gemini ASR',
    }
    return mapping.get((oss_asr or '').strip().lower(), oss_asr or 'Whisper')


def format_three_way_report(row: pd.Series, config: BenchmarkConfig) -> str:
    sep = '=' * 64
    dash = '-' * 64
    asr_label = _oss_asr_label(config.oss_asr)
    path3_label = (
        f'OPEN SOURCE ({config.oss_backend} vision + {asr_label} + local synthesis)'
    )
    vision_cost = float(row.get('gemini_vision_track_cost', 0) or 0)
    asr_cost = float(row.get('gemini_asr_cost', 0) or 0)
    synth_cost = float(row.get('gemini_synthesis_cost', 0) or 0)
    vision_frames = int(row.get('keyframe_count', 0) or _frame_count_from_row(row) or 0)
    synth_frames = int(row.get('gemini_synthesis_frame_count', 0) or 0)
    fal_cost = row.get('fal_cost')
    nova_cost_val = row.get('nova_cost')
    lines = [
        sep,
        f'QUERY: {row.get("query", "")}',
        dash,
        'COSTS (heuristic; uses API usage_metadata when available)',
        f'  native_cost                  ${float(row.get("native_cost", 0) or 0):.3f}',
        f'  gemini_orchestrated_total    '
        f'${float(row.get("gemini_orchestrated_total", 0) or 0):.3f}',
        f'    vision_track               ${vision_cost:.3f}'
        + (f'  ({vision_frames} API frames)' if vision_frames else ''),
        f'    asr                        ${asr_cost:.3f}',
        f'    synthesis                  ${synth_cost:.3f}'
        + (f'  ({synth_frames} frames in context)' if synth_frames else ''),
        f'  oss_cost                     ${float(row.get("oss_cost", 0) or 0):.3f}',
    ]
    if fal_cost is not None and not (isinstance(fal_cost, float) and pd.isna(fal_cost)):
        lines.append(
            f'  fal_cost                     ${float(fal_cost or 0):.3f}'
            '  (input capped at 120s; API max ~122s)'
        )
    if nova_cost_val is not None and not (
        isinstance(nova_cost_val, float) and pd.isna(nova_cost_val)
    ):
        lines.append(f'  nova_cost                    ${float(nova_cost_val or 0):.3f}')
    lines.append(
        '  cost_delta_native_vs_gemini  '
        f'${float(row.get("cost_delta_native_vs_gemini", 0) or 0):.3f}'
    )
    if row.get('cost_delta_native_vs_fal') is not None and not pd.isna(
        row.get('cost_delta_native_vs_fal')
    ):
        lines.append(
            '  cost_delta_native_vs_fal     '
            f'${float(row.get("cost_delta_native_vs_fal", 0) or 0):.3f}'
        )
    if row.get('cost_delta_native_vs_nova') is not None and not pd.isna(
        row.get('cost_delta_native_vs_nova')
    ):
        lines.append(
            '  cost_delta_native_vs_nova    '
            f'${float(row.get("cost_delta_native_vs_nova", 0) or 0):.3f}'
        )
    lines.extend(
        [
            sep,
            f'PATH 1 — NATIVE GEMINI ({config.gemini_model} on full video)',
            str(row.get('native_insight', '') or ''),
            '',
            'PATH 2 — GEMINI ORCHESTRATED (keyframes + gemini.transcribe + multimodal synthesis)',
            str(row.get('gemini_orchestrated_insight', '') or ''),
            '',
            f'PATH 3 — {path3_label}',
            str(row.get('oss_insight', '') or ''),
        ]
    )
    if config.enable_fal or row.get('fal_insight'):
        lines.extend(
            [
                '',
                'PATH 4 — NATIVE FAL (fal-ai/video-understanding; input capped at 120s)',
                str(row.get('fal_insight', '') or '(skipped — set FAL_KEY to enable)'),
            ]
        )
    if config.enable_nova or row.get('nova_insight'):
        lines.extend(
            [
                '',
                f'PATH 5 — NATIVE NOVA ({config.nova_model_id} via Bedrock)',
                str(row.get('nova_insight', '') or '(skipped — set AWS/Bedrock creds to enable)'),
            ]
        )
    lines.append(sep)
    return '\n'.join(lines)


def print_three_way_comparison(config: BenchmarkConfig) -> None:
    row = _latest_video_row()
    if row is None:
        print('No video_sources rows to compare.')
        return
    print(format_three_way_report(row, config))


def _git_commit() -> str | None:
    try:
        result = subprocess.run(
            ['git', 'rev-parse', 'HEAD'],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def export_run(
    config: BenchmarkConfig,
    export_dir: Path,
    video_path: str,
    query: str,
) -> Path:
    row = _latest_video_row()
    if row is None:
        raise RuntimeError('No results to export')

    ts = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    out = export_dir / ts
    out.mkdir(parents=True, exist_ok=True)

    frame_count = _frame_count_from_row(row)
    synth_frame_count = _synthesis_frame_count_from_row(row)
    audio_chunk_count = _audio_chunk_count_from_row(row)
    # Attach counts so format_three_way_report can annotate cost lines.
    row = row.copy()
    row['keyframe_count'] = frame_count
    row['gemini_synthesis_frame_count'] = synth_frame_count

    manifest = {
        'timestamp_utc': ts,
        'python_version': sys.version,
        'platform': platform.platform(),
        'git_commit': _git_commit(),
        'video_path': video_path,
        'query': query,
        'config': config_manifest_dict(config),
    }
    summary = {
        'query': row.get('query', ''),
        'video_duration_sec': float(row.get('video_duration_sec', 0) or 0),
        'keyframe_count': frame_count,
        'gemini_synthesis_frame_count': synth_frame_count,
        'audio_chunk_count': audio_chunk_count,
        'native_cost': float(row.get('native_cost', 0) or 0),
        'gemini_orchestrated_total': float(row.get('gemini_orchestrated_total', 0) or 0),
        'gemini_vision_track_cost': float(row.get('gemini_vision_track_cost', 0) or 0),
        'gemini_asr_cost': float(row.get('gemini_asr_cost', 0) or 0),
        'gemini_synthesis_cost': float(row.get('gemini_synthesis_cost', 0) or 0),
        'oss_cost': float(row.get('oss_cost', 0) or 0),
        'cost_delta_native_vs_gemini': float(row.get('cost_delta_native_vs_gemini', 0) or 0),
        'cost_note': (
            'Heuristic estimates; native/synthesis/vision use usage_metadata when present. '
            'fal_cost is $0.01 per 5s on input capped at 120s (API max ~122s); '
            'nova_cost uses Bedrock token rates (default Nova Pro). '
            'vision_track sums all vision API frames; synthesis uses the capped frame context.'
        ),
    }
    if (
        'fal_cost' in row.index
        and row.get('fal_cost') is not None
        and not pd.isna(row.get('fal_cost'))
    ):
        summary['fal_cost'] = float(row.get('fal_cost') or 0)
        summary['cost_delta_native_vs_fal'] = float(row.get('cost_delta_native_vs_fal', 0) or 0)
    if 'nova_cost' in row.index and row.get('nova_cost') is not None and not pd.isna(
        row.get('nova_cost')
    ):
        summary['nova_cost'] = float(row.get('nova_cost') or 0)
        summary['cost_delta_native_vs_nova'] = float(row.get('cost_delta_native_vs_nova', 0) or 0)

    insights = {
        'native_insight': row.get('native_insight', ''),
        'gemini_orchestrated_insight': row.get('gemini_orchestrated_insight', ''),
        'oss_insight': row.get('oss_insight', ''),
    }
    if 'fal_insight' in row.index:
        insights['fal_insight'] = row.get('fal_insight', '')
    if 'nova_insight' in row.index:
        insights['nova_insight'] = row.get('nova_insight', '')

    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    (out / 'summary.json').write_text(json.dumps(summary, indent=2))
    (out / 'insights.json').write_text(json.dumps(insights, indent=2))
    (out / 'REPORT.md').write_text(format_three_way_report(row, config))

    frame_df = build_comparison_dataframe()
    frame_df.to_csv(out / 'keyframes.csv', index=False)

    return out
