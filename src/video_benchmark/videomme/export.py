"""Export Video-MME dev results under results/videomme-dev/<timestamp>/."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from video_benchmark.config import PROJECT_ROOT, BenchmarkConfig, config_manifest_dict
from video_benchmark.videomme.scoring import summarize_scores


def export_run(
    *,
    predictions: list[dict[str, Any]],
    video_shared: dict[str, dict[str, Any]],
    config: BenchmarkConfig,
    seed: int,
    n: int,
    export_base: Path | None = None,
    paths: set[str] | None = None,
) -> Path:
    ts = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    out = (export_base or (PROJECT_ROOT / 'results' / 'videomme-dev')) / ts
    out.mkdir(parents=True, exist_ok=True)

    summary = summarize_scores(predictions)
    summary['seed'] = seed
    summary['n_requested'] = n
    summary['n_videos'] = len(video_shared)
    summary['gemini_model'] = config.gemini_model
    summary['nova_model_id'] = config.nova_model_id
    active_paths = sorted(paths) if paths else ['1', '2', '3', '5']
    summary['active_paths'] = active_paths

    manifest = {
        'timestamp_utc': ts,
        'seed': seed,
        'n': n,
        'paths': active_paths,
        'config': config_manifest_dict(config),
        'video_ids': sorted(video_shared.keys()),
        'notes': {
            'path3_asr': 'shared Gemini ASR (not WhisperX)',
            'fal': 'omitted from Video-MME (120s cap)',
        },
    }
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    (out / 'summary.json').write_text(json.dumps(summary, indent=2))

    with (out / 'predictions.jsonl').open('w') as fh:
        for row in predictions:
            fh.write(json.dumps(row, ensure_ascii=False) + '\n')

    shared_export = {
        vid: {
            'shared_cost': meta.get('shared_cost'),
            'vision_cost': meta.get('vision_cost'),
            'asr_cost': meta.get('asr_cost'),
            'oss_shared_cost': meta.get('oss_shared_cost'),
            'video_duration_sec': meta.get('video_duration_sec'),
        }
        for vid, meta in video_shared.items()
    }
    (out / 'video_shared_costs.json').write_text(json.dumps(shared_export, indent=2))

    lines = [
        '# Video-MME Dev Slice Report',
        '',
        f'- Questions: {summary["n"]}',
        f'- Videos: {summary["n_videos"]}',
        f'- Gemini model: {config.gemini_model}',
        f'- Nova model: {config.nova_model_id}',
        f'- Paths: {", ".join(active_paths)}',
        f'- Seed: {seed}',
        '- Path 3 ASR: shared Gemini (not WhisperX); fal omitted',
        '',
        '## Accuracy',
        f'- Path 1 native Gemini: {_fmt_acc(summary.get("native_accuracy"))} '
        f'({summary.get("native_correct", 0)}/{summary["n"]})',
        f'- Path 2 orchestrated Gemini: {_fmt_acc(summary.get("orchestrated_accuracy"))} '
        f'({summary.get("orchestrated_correct", 0)}/{summary["n"]})',
        f'- Path 3 OSS (local VLM+7B): {_fmt_acc(summary.get("oss_accuracy"))} '
        f'({summary.get("oss_correct", 0)}/{summary["n"]})',
        f'- Path 5 Nova: {_fmt_acc(summary.get("nova_accuracy"))} '
        f'({summary.get("nova_correct", 0)}/{summary["n"]})',
        f'- Path 1 ingest_failed: {summary.get("native_ingest_failed", 0)}',
        f'- Path 5 ingest_failed: {summary.get("nova_ingest_failed", 0)}',
        '',
        '## Cost',
        f'- Path 1 total: ${_fmt_num(summary.get("native_total_cost"))}',
        f'- Path 2 total (amortized shared + synth): '
        f'${_fmt_num(summary.get("orchestrated_total_cost"))}',
        f'- Path 3 total (API $0): ${_fmt_num(summary.get("oss_total_cost"))}',
        f'- Path 5 total: ${_fmt_num(summary.get("nova_total_cost"))}',
        f'- Path 1 $/correct: {_fmt_money(summary.get("native_cost_per_correct"))}',
        f'- Path 2 $/correct: {_fmt_money(summary.get("orchestrated_cost_per_correct"))}',
        f'- Path 3 $/correct: {_fmt_money(summary.get("oss_cost_per_correct"))}',
        f'- Path 5 $/correct: {_fmt_money(summary.get("nova_cost_per_correct"))}',
        '',
        '## By duration',
    ]
    for dur, block in (summary.get('by_duration') or {}).items():
        lines.append(
            f'- {dur}: n={block["n"]} '
            f'native={_fmt_acc(block.get("native_acc"))} '
            f'orch={_fmt_acc(block.get("orchestrated_acc"))} '
            f'oss={_fmt_acc(block.get("oss_acc"))} '
            f'nova={_fmt_acc(block.get("nova_acc"))}'
        )
    lines.extend(['', '## Per-question', ''])
    for p in predictions:
        lines.append(
            f'- {p["question_id"]} [{p.get("duration")}] gold={p["gold"]} '
            f'n={p.get("native_letter")}{"Y" if p.get("native_correct") else "N"} '
            f'o={p.get("orchestrated_letter")}{"Y" if p.get("orchestrated_correct") else "N"} '
            f'oss={p.get("oss_letter")}{"Y" if p.get("oss_correct") else "N"} '
            f'nova={p.get("nova_letter")}{"Y" if p.get("nova_correct") else "N"}'
        )
    (out / 'REPORT.md').write_text('\n'.join(lines) + '\n')
    return out


def _fmt_acc(v: float | None) -> str:
    return 'n/a' if v is None else f'{v:.3f}'


def _fmt_money(v: float | None) -> str:
    return 'n/a' if v is None else f'${v:.4f}'


def _fmt_num(v: float | None) -> str:
    return '0.0000' if v is None else f'{float(v):.4f}'
