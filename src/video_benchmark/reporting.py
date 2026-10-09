"""Export one run from the catalog: costs with token usage, answers, heuristic scores."""

from __future__ import annotations

import csv
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pixeltable as pxt

from video_benchmark import pricing, provenance
from video_benchmark.config import PROJECT_ROOT, BenchmarkConfig, config_manifest_dict
from video_benchmark.paths import PATH_LABELS
from video_benchmark.runner import table
from video_benchmark.schema import PathPlan
from video_benchmark.scoring import score_answer

# path -> (table, answer column, cost column, per-call response columns)
PATH_COLUMNS = {
    '1': ('runs', 'native_answer', 'native_cost', ('native_response',)),
    '1L': ('runs', 'native_low_answer', 'native_low_cost', ('native_low_response',)),
    '2': ('syntheses', 'gemini_answer', 'gemini_total_cost', ('gemini_response',)),
    '3': ('syntheses', 'oss_answer', 'oss_cost', ('oss_answer',)),
    '4': ('runs', 'fal_answer', 'fal_cost', ('fal_response',)),
    '5': ('runs', 'nova_answer', 'nova_cost', ('nova_response',)),
}
USAGE_COLUMNS = {
    '1': ('runs', 'native_usage'),
    '1L': ('runs', 'native_low_usage'),
    '5': ('runs', 'nova_usage'),
}


def _row(name: str, run_id: str, columns: set[str], call_columns: set[str]) -> dict[str, Any]:
    """One row's values, plus `<col>__error` (the stored error message) for each call column."""
    tbl = table(name)
    select = {col: getattr(tbl, col) for col in sorted(columns | call_columns)}
    select.update({f'{col}__error': getattr(tbl, col).errormsg for col in sorted(call_columns)})
    rows = tbl.where(tbl.run_id == run_id).select(**select).collect()
    if len(rows) == 0:
        raise LookupError(f'No {name} row for run {run_id}')
    return rows[0]


def add_usage(total: dict, usage: dict | None) -> dict:
    """Sum token counts, including the per-modality breakdowns."""
    if not usage:
        return total
    for key, value in usage.items():
        if isinstance(value, dict):
            bucket = total.setdefault(key, {})
            for modality, tokens in value.items():
                bucket[modality] = bucket.get(modality, 0) + int(tokens or 0)
        else:
            total[key] = total.get(key, 0) + int(value or 0)
    return total


def list_cost(usage: dict | None, model: str) -> float | None:
    """Gemini cost of these tokens without the implicit-cache discount (list price)."""
    if not usage:
        return None
    return pricing.gemini_cost_impl(pricing.uncached_usage_impl(usage), model)


def _stage(rows: list[dict], cost_key: str, usage_key: str, model: str) -> dict[str, Any]:
    usage: dict = {}
    for row in rows:
        add_usage(usage, row.get(usage_key))
    return {
        'calls': len(rows),
        'failed_calls': sum(bool(row.get('error')) for row in rows),
        'unknown_cost_calls': sum(row.get(cost_key) is None for row in rows),
        # Billed but no text: a recitation or safety stop, which raises no error.
        'empty_outputs': sum(
            1 for row in rows if row.get(cost_key) is not None and not row['text']
        ),
        'cost_usd': (sum(row[cost_key] for row in rows)
                     if all(row.get(cost_key) is not None for row in rows) else None),
        'response_accounted_cost_usd': sum(row.get(cost_key) or 0.0 for row in rows),
        'list_cost_usd': ((list_cost(usage, model) or 0.0)
                          if all(row.get(usage_key) is not None for row in rows) else None),
        'usage': usage,
    }


def _orchestrated_stages(run_id: str, synthesis: dict, model: str) -> dict[str, Any]:
    kf = table('keyframes')
    frames = (
        kf.where(kf.run_id == run_id)
        .select(cost=kf.gemini_caption_cost, usage=kf.gemini_caption_usage, text=kf.gemini_caption,
                error=kf.gemini_caption_response.errormsg)
        .collect()
    )
    ac = table('audio_chunks')
    chunks = (
        ac.where(ac.run_id == run_id)
        .select(cost=ac.gemini_asr_cost, usage=ac.gemini_asr_usage, text=ac.gemini_transcript,
                error=ac.gemini_asr_response.errormsg)
        .collect()
    )
    return {
        'captions': _stage(list(frames), 'cost', 'usage', model),
        'asr': _stage(list(chunks), 'cost', 'usage', model),
        'synthesis': {
            'calls': 1,
            'failed_calls': int(bool(synthesis.get('gemini_response__error'))),
            'unknown_cost_calls': int(synthesis.get('gemini_synthesis_cost') is None),
            'cost_usd': synthesis.get('gemini_synthesis_cost'),
            'list_cost_usd': list_cost(synthesis.get('gemini_synthesis_usage'), model),
            'usage': synthesis.get('gemini_synthesis_usage') or {},
            'frames_in_evidence': len(synthesis.get('gemini_selected') or []),
            'images_attached': len(synthesis.get('gemini_attached') or []),
        },
    }


def collect_run(run_id: str, plan: PathPlan, config: BenchmarkConfig) -> dict[str, Any]:
    """Everything the export needs for one run, read back from the catalog.

    `cost_usd` is billed; `list_cost_usd` prices the same tokens without Gemini's
    implicit-cache discount, which varies between identical runs.
    """
    paths = plan.enabled()
    wanted: dict[str, set[str]] = {'runs': {'query', 'duration_sec'}}
    calls: dict[str, set[str]] = {'runs': set()}
    for path in paths:
        tbl_name, answer, cost, call_cols = PATH_COLUMNS[path]
        wanted.setdefault(tbl_name, set()).update({answer, cost})
        calls.setdefault(tbl_name, set()).update((*call_cols, cost))
        if path in USAGE_COLUMNS:
            wanted['runs'].add(USAGE_COLUMNS[path][1])
            calls['runs'].add(USAGE_COLUMNS[path][1])
    if plan.orchestrated:
        wanted['syntheses'].update(
            {
                'gemini_synthesis_cost',
                'gemini_synthesis_usage',
                'gemini_selected',
                'gemini_attached',
            }
        )
    rows = {name: _row(name, run_id, cols, calls[name]) for name, cols in wanted.items()}
    out: dict[str, Any] = {
        'run_id': run_id,
        'query': rows['runs']['query'],
        'duration_sec': rows['runs']['duration_sec'],
        'paths': {},
    }
    for path in paths:
        tbl_name, answer_col, cost_col, call_cols = PATH_COLUMNS[path]
        row = rows[tbl_name]
        answer = row.get(answer_col) or ''
        error_columns = {*call_cols, cost_col}
        if path in USAGE_COLUMNS:
            error_columns.add(USAGE_COLUMNS[path][1])
        entry: dict[str, Any] = {
            'label': PATH_LABELS[path],
            'answer': answer,
            'words': len(answer.split()),
            'cost_usd': row.get(cost_col),
            'cost_status': 'known' if row.get(cost_col) is not None else 'unknown',
            'errors': {c: row[f'{c}__error'] for c in error_columns
                       if row.get(f'{c}__error')},
            'scores': score_answer(answer),
        }
        entry['list_cost_usd'] = entry['cost_usd']  # no cache discount: fal, Nova, local
        if path in USAGE_COLUMNS:
            entry['usage'] = rows['runs'].get(USAGE_COLUMNS[path][1]) or {}
            if path in {'1', '1L'}:
                entry['list_cost_usd'] = list_cost(entry['usage'], config.gemini_model)
        if path == '2':
            entry['stages'] = _orchestrated_stages(run_id, rows['syntheses'], config.gemini_model)
            stages = list(entry['stages'].values())
            if any(s['cost_usd'] is None for s in stages):
                entry['cost_usd'], entry['cost_status'] = None, 'unknown'
            entry['list_cost_usd'] = (
                sum(s['list_cost_usd'] for s in stages)
                if all(s['list_cost_usd'] is not None for s in stages) else None
            )
        entry['response_accounted_cost_usd'] = (
            sum(stage.get('response_accounted_cost_usd', stage['cost_usd'] or 0.0)
                for stage in entry['stages'].values())
            if path == '2' else entry['cost_usd'] or 0.0
        )
        out['paths'][path] = entry
    return out


def keyframe_rows(run_id: str, plan: PathPlan) -> list[dict[str, Any]]:
    if not plan.modular:
        return []
    kf = table('keyframes')
    select: dict[str, Any] = {'position_sec': kf.position_sec}
    if plan.orchestrated:
        select.update(gemini_caption=kf.gemini_caption, gemini_caption_cost=kf.gemini_caption_cost)
    if plan.oss:
        select['oss_caption'] = kf.oss_caption
    frames = list(
        kf.where(kf.run_id == run_id).order_by(kf.position_sec).select(**select).collect()
    )
    if plan.orchestrated:
        syn = table('syntheses')
        chosen = syn.where(syn.run_id == run_id).select(syn.gemini_selected, syn.gemini_attached)
        chosen_row = chosen.collect()[0]
        selected = {f['position_sec'] for f in chosen_row['gemini_selected'] or []}
        attached = {f['position_sec'] for f in chosen_row['gemini_attached'] or []}
        for frame in frames:
            frame['selected'] = frame['position_sec'] in selected
            frame['image_attached'] = frame['position_sec'] in attached
    return frames


def _money(value: float | None) -> str:
    return 'unknown' if value is None else f'${value:.4f}'


def _tokens(usage: dict | None) -> str:
    if not usage:
        return '-'
    by_modality = usage.get('input_by_modality') or {}
    modal = ', '.join(f'{m.lower()} {n:,}' for m, n in sorted(by_modality.items()))
    parts = [f'in {usage.get("input_tokens", 0):,}' + (f' ({modal})' if modal else '')]
    parts.append(f'out {usage.get("output_tokens", 0):,}')
    if usage.get('thinking_tokens'):
        parts.append(f'thinking {usage["thinking_tokens"]:,}')
    if usage.get('cached_tokens'):
        parts.append(f'cached {usage["cached_tokens"]:,}')
    return '; '.join(parts)


def format_report(run: dict[str, Any], config: BenchmarkConfig) -> str:
    lines = [
        f'# Run {run["run_id"]}',
        '',
        f'- Query: {run["query"]}',
        f'- Video duration: {float(run["duration_sec"] or 0):.1f} s',
        f'- Gemini model: {config.gemini_model}; prices as of {pricing.PRICES_AS_OF}',
        '',
        '## Cost',
        '',
        'Billed cost includes Gemini implicit-cache discounts; list cost prices the same tokens '
        'without them.',
        '',
        '| Path | Billed | List | Tokens |',
        '|------|-------:|-----:|--------|',
    ]
    for path, entry in run['paths'].items():
        lines.append(
            f'| {path} {entry["label"]} | {_money(entry["cost_usd"])} | '
            f'{_money(entry["list_cost_usd"])} | {_tokens(entry.get("usage"))} |'
        )
        for stage, info in (entry.get('stages') or {}).items():
            lost = [
                f'{info[key]} {word}'
                for key, word in (('failed_calls', 'failed'), ('empty_outputs', 'empty'))
                if info.get(key)
            ]
            calls = f'{info["calls"]} call{"s" * (info["calls"] != 1)}' + ''.join(
                f', {item}' for item in lost
            )
            lines.append(
                f'| &nbsp;&nbsp;{stage} ({calls}) | '
                f'{_money(info["cost_usd"])} | {_money(info["list_cost_usd"])} | '
                f'{_tokens(info["usage"])} |'
            )
    lines += ['', '## Heuristic scores', '']
    score_names = list(next(iter(run['paths'].values()))['scores']) if run['paths'] else []
    lines.append('| Path | words | ' + ' | '.join(score_names) + ' |')
    lines.append('|------|------:|' + '|'.join(':-:' for _ in score_names) + '|')
    for path, entry in run['paths'].items():
        marks = ' | '.join('Y' if entry['scores'][s] else '-' for s in score_names)
        lines.append(f'| {path} | {entry["words"]} | {marks} |')
    for path, entry in run['paths'].items():
        lines += ['', f'## Path {path}: {entry["label"]}', '']
        for column, message in entry['errors'].items():
            lines.append(f'> {column} failed: {message}')
        lines.append(entry['answer'] or '(no answer)')
    return '\n'.join(lines) + '\n'


def environment() -> dict[str, Any]:
    """Provenance recorded in every manifest."""
    try:
        commit = subprocess.run(
            ['git', 'rev-parse', 'HEAD'],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        dirty = bool(subprocess.run(
            ['git', 'status', '--porcelain', '--untracked-files=normal'], cwd=PROJECT_ROOT,
            capture_output=True, text=True, check=True,
        ).stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError):
        commit = None
        dirty = None
    return {
        'git_commit': commit,
        'git_dirty': dirty,
        'source_sha256': provenance.source_identity(),
        'package_versions': provenance.package_versions(),
        'python_version': sys.version,
        'platform': platform.platform(),
        'pixeltable_version': pxt.__version__,
    }


def export_run(
    run_id: str, plan: PathPlan, config: BenchmarkConfig, video_path: str, export_dir: Path
) -> Path:
    run = collect_run(run_id, plan, config)
    out = export_dir / run_id
    out.mkdir(parents=True, exist_ok=True)
    manifest = {
        'run_id': run_id,
        'exported_utc': f'{datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ}',
        **environment(),
        'video_path': video_path,
        'video_identity': provenance.media_identity(video_path),
        'paths': list(run['paths']),
        'config': config_manifest_dict(config),
        'prices': {
            'as_of': pricing.PRICES_AS_OF,
            'sources': pricing.PRICE_SOURCES,
            'gemini_usd_per_1m': {
                m: {'input': r.input, 'cached_input': r.cached_input, 'output': r.output}
                for m, r in pricing.GEMINI_RATES.items()
            },
            'nova_usd_per_1m': pricing.NOVA_RATES,
            'fal_usd_per_5s': pricing.FAL_USD_PER_5_SEC,
        },
    }
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    (out / 'summary.json').write_text(json.dumps(run, indent=2, default=str) + '\n')
    (out / 'REPORT.md').write_text(format_report(run, config))
    frames = keyframe_rows(run_id, plan)
    if frames:
        with (out / 'keyframes.csv').open('w', newline='') as fh:
            writer = csv.DictWriter(fh, fieldnames=list(frames[0]))
            writer.writeheader()
            writer.writerows(frames)
    return out
