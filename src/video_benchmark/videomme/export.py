"""Summarize and export a Video-MME run: accuracy with intervals, paired tests, cost."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from typing import Any

from video_benchmark import pricing
from video_benchmark.config import BenchmarkConfig, config_manifest_dict
from video_benchmark.paths import PATH_LABELS
from video_benchmark.reporting import environment
from video_benchmark.stats import (
    cluster_bootstrap,
    difference_of,
    mcnemar_exact,
    mean_of,
    paired_cluster_test,
    wilson_interval,
)
from video_benchmark.videomme.runner import field
from video_benchmark.videomme.sample import HF_CONFIG, HF_DATASET, HF_REVISION

BUCKETS = ('short', 'medium', 'long')


def attempted(rows: list[dict[str, Any]], *paths: str) -> list[dict[str, Any]]:
    """Rows every given path ran on (Nova skips videos over Bedrock's inline limit)."""
    return [r for r in rows if all(r.get(field(p, 'attempted'), True) for p in paths)]


def _accuracy_block(
    rows: list[dict[str, Any]], path: str, *, intervals: bool = True
) -> dict[str, Any]:
    k = sum(1 for row in rows if row.get(field(path, 'correct')))
    n = len(rows)
    unknown = sum(row[field(path, 'cost')] is None for row in rows)
    total = sum(row[field(path, 'cost')] or 0.0 for row in rows)
    list_unknown = sum(row[field(path, 'list_cost')] is None for row in rows)
    list_total = sum(row[field(path, 'list_cost')] or 0.0 for row in rows)
    return {
        'n': n,
        'correct': k,
        'accuracy': k / n if n else None,
        'accuracy_ci95': (
            cluster_bootstrap(
                rows, 'video_id', lambda sample: sum(bool(r.get(field(path, 'correct')))
                for r in sample) / len(sample)
            ) if n and intervals else None
        ),
        'accuracy_wilson_ci95': wilson_interval(k, n) if n and intervals else None,
        'unknown_cost_questions': unknown,
        'response_accounted_cost_usd': total,
        'mean_cost_usd': total / n if n and not unknown else None,
        'total_cost_usd': total if not unknown else None,
        'cost_per_correct_usd': total / k if k and not unknown else None,
        'mean_list_cost_usd': list_total / n if n and not list_unknown else None,
        'total_list_cost_usd': list_total if not list_unknown else None,
    }


def summarize(predictions: list[dict[str, Any]], paths: list[str]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        'n_questions': len(predictions),
        'n_videos': len({row['video_id'] for row in predictions}),
        'paths': {},
        'comparisons': [],
        'inference': {
            'accuracy_ci95': '95% percentile bootstrap, resampling whole videos, seed 0',
            'paired_p': 'exact paired label exchange by video; exploratory, unadjusted',
            'mcnemar_p': 'question-level diagnostic; ignores within-video dependence',
            'missing_outcomes': 'wrong on every attempted question, including intervals',
        },
    }
    for path in paths:
        rows = attempted(predictions, path)
        block = _accuracy_block(rows, path)
        block.update(
            label=PATH_LABELS[path],
            failed_calls=sum(1 for row in rows if row.get(field(path, 'error'))),
            no_letter=sum(1 for row in rows if row.get(field(path, 'letter')) is None),
            shared_cost_usd=sum(row[field(path, 'shared_cost')] or 0.0 for row in rows),
            accounting_errors=sum(bool(row.get(field(path, 'accounting_error'))) for row in rows),
            mean_cost_ci95=(
                cluster_bootstrap(rows, 'video_id', mean_of(field(path, 'cost')))
                if rows and block['total_cost_usd'] is not None else None
            ),
            mean_list_cost_ci95=(
                cluster_bootstrap(rows, 'video_id', mean_of(field(path, 'list_cost')))
                if rows and block['total_list_cost_usd'] is not None else None
            ),
            by_duration={
                bucket: _accuracy_block([r for r in rows if r['duration_bucket'] == bucket], path)
                for bucket in BUCKETS
            },
        )
        summary['paths'][path] = block
    for a, b in combinations(paths, 2):
        rows = [
            {**row, field(a, 'correct'): bool(row.get(field(a, 'correct'))),
             field(b, 'correct'): bool(row.get(field(b, 'correct')))}
            for row in attempted(predictions, a, b)
        ]
        ca, cb = field(a, 'correct'), field(b, 'correct')
        a_only = sum(1 for r in rows if r.get(ca) and not r.get(cb))
        b_only = sum(1 for r in rows if r.get(cb) and not r.get(ca))
        pa = _accuracy_block(rows, a, intervals=False)
        pb = _accuracy_block(rows, b, intervals=False)
        summary['comparisons'].append(
            {
                'a': a,
                'b': b,
                'n': len(rows),
                'accuracy_diff': pa['accuracy'] - pb['accuracy'] if rows else None,
                'accuracy_diff_ci95': (
                    cluster_bootstrap(rows, 'video_id', difference_of(mean_of(ca), mean_of(cb)))
                    if rows else None
                ),
                'a_only_correct': a_only,
                'b_only_correct': b_only,
                'mcnemar_p': mcnemar_exact(a_only, b_only),
                'paired_cluster_p': paired_cluster_test(rows, 'video_id', ca, cb),
                'cost_ratio_a_over_b': (
                    pa['total_cost_usd'] / pb['total_cost_usd']
                    if pa['total_cost_usd'] is not None and pb['total_cost_usd'] else None
                ),
                'list_cost_ratio_a_over_b': (
                    pa['total_list_cost_usd'] / pb['total_list_cost_usd']
                    if pa['total_list_cost_usd'] is not None and pb['total_list_cost_usd']
                    else None
                ),
            }
        )
    return summary


def evidence_summary(videos: list[dict[str, Any]]) -> dict[str, Any]:
    """Totals of the shared evidence calls: how many ran, raised, or returned no text."""
    out: dict[str, Any] = {}
    for stage in ('caption', 'asr'):
        if videos and f'{stage}_calls' in videos[0]:
            out[stage] = {
                k: sum(v[f'{stage}_{k}'] for v in videos) for k in ('calls', 'failed', 'empty')
            }
            out[stage]['list_cost_usd'] = sum(v[f'{stage}_list_cost'] for v in videos)
    return out


def _pct(value: float | None) -> str:
    return 'n/a' if value is None else f'{100 * value:.1f}%'


def _ci(interval: tuple[float, float] | None, scale: float = 100.0, fmt: str = '.1f') -> str:
    if interval is None:
        return 'n/a'
    lo, hi = interval
    return f'[{scale * lo:{fmt}}, {scale * hi:{fmt}}]'


def _usd(value: float | None, digits: int = 4) -> str:
    return 'n/a' if value is None else f'${value:.{digits}f}'


def format_report(summary: dict[str, Any], config: BenchmarkConfig, seed: int) -> str:
    lines = [
        '# Video-MME run',
        '',
        f'- Questions: {summary["n_questions"]} from {summary["n_videos"]} videos (seed {seed})',
        f'- Gemini model: {config.gemini_model}; Nova model: {config.nova_model_id}',
        f'- Frames: {config.vision_sample_keyframes} sampled, {config.frame_select_budget} kept; '
        f'prices as of {pricing.PRICES_AS_OF}',
        '- Costs estimate returned token usage; retries, interruptions, and missing usage '
        'may add unrecorded spend. Unknown costs are n/a, not zero.',
    ]
    for stage, name in (('caption', 'captions'), ('asr', 'transcripts')):
        if stage in summary.get('evidence', {}):
            e = summary['evidence'][stage]
            lines.append(
                f'- Evidence {name}: {e["calls"]} calls, {e["failed"]} failed, '
                f'{e["empty"]} returned no text'
            )
    lines += [
        '',
        '## Accuracy and cost',
        '',
        'Response-accounted cost estimates returned token usage after cache discounts; '
        'list cost prices the same tokens without them. Missing usage makes totals unknown.',
        '',
        '| Path | n | Accuracy [95% CI] | Short | Medium | Long | $/question | list $/question '
        '| $/correct | Failed |',
        '|------|--:|------------------|------:|-------:|-----:|-----------:|------:|----------:'
        '|-------:|',
    ]
    for path, block in summary['paths'].items():
        by = block['by_duration']
        lines.append(
            f'| {path} {block["label"]} | {block["n"]} | {_pct(block["accuracy"])} '
            f'{_ci(block["accuracy_ci95"])} | {_pct(by["short"]["accuracy"])} | '
            f'{_pct(by["medium"]["accuracy"])} | {_pct(by["long"]["accuracy"])} | '
            f'{_usd(block["mean_cost_usd"])} | {_usd(block["mean_list_cost_usd"])} | '
            f'{_usd(block["cost_per_correct_usd"])} | {block["failed_calls"]} |'
        )
    lines += [
        '',
        '## Paired comparisons',
        '',
        'Accuracy and difference intervals resample whole videos. Paired p exchanges path '
        'labels for whole videos; exploratory comparisons are unadjusted.',
        '',
        '| A vs B | n | Accuracy A - B [95% CI] | A only | B only | Paired video p | Cost A / B |',
        '|--------|--:|------------------------|-------:|-------:|----------:|-----------:|',
    ]
    for c in summary['comparisons']:
        if not c['n']:
            continue
        ratio = 'n/a' if c['cost_ratio_a_over_b'] is None else f'{c["cost_ratio_a_over_b"]:.2f}x'
        lines.append(
            f'| {c["a"]} vs {c["b"]} | {c["n"]} | {100 * c["accuracy_diff"]:+.1f} pp '
            f'{_ci(c["accuracy_diff_ci95"])} | {c["a_only_correct"]} | {c["b_only_correct"]} | '
            f'{c["paired_cluster_p"]:.3f} | {ratio} |'
        )
    return '\n'.join(lines) + '\n'


def export_run(
    *,
    predictions: list[dict[str, Any]],
    videos: list[dict[str, Any]],
    paths: list[str],
    config: BenchmarkConfig,
    seed: int,
    n: int,
    export_base: Path,
) -> Path:
    out = export_base / f'{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}'
    out.mkdir(parents=True, exist_ok=True)
    summary = summarize(predictions, paths)
    summary['evidence'] = evidence_summary(videos)
    manifest = {
        'exported_utc': f'{datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ}',
        **environment(),
        'seed': seed,
        'n_requested': n,
        'dataset': HF_DATASET,
        'dataset_config': HF_CONFIG,
        'dataset_revision': HF_REVISION,
        'paths': paths,
        'video_ids': sorted({row['video_id'] for row in predictions}),
        'config': config_manifest_dict(config),
        'prices_as_of': pricing.PRICES_AS_OF,
        'price_sources': pricing.PRICE_SOURCES,
    }
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    (out / 'summary.json').write_text(json.dumps(summary, indent=2, allow_nan=False) + '\n')
    for name, rows in (('predictions', predictions), ('videos', videos)):
        with (out / f'{name}.jsonl').open('w') as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False, default=str) + '\n')
    (out / 'REPORT.md').write_text(format_report(summary, config, seed))
    return out
