"""Run Video-MME: sample questions, insert videos then questions, read predictions.

Rows already in the catalog are not inserted again, so an interrupted run resumes where it
stopped and a rerun costs nothing.
"""

from __future__ import annotations

import os
import sys
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any

import pixeltable as pxt

from video_benchmark.accounting import cost_totals
from video_benchmark.config import BenchmarkConfig
from video_benchmark.paths import parse_paths as parse_path_spec
from video_benchmark.pricing import gemini_cost_impl, nova_cost_impl, uncached_usage_impl
from video_benchmark.provenance import input_identity, media_identity
from video_benchmark.reporting import add_usage
from video_benchmark.runner import retry_column_once
from video_benchmark.schema import PathPlan, plan_paths
from video_benchmark.videomme import DEFAULT_N, DEFAULT_SEED, VIDEOME_ASSETS
from video_benchmark.videomme.download import download_videos
from video_benchmark.videomme.sample import (
    HF_REVISION,
    load_manifest,
    load_videomme_rows,
    sample_questions,
    save_manifest,
    unique_videos,
)
from video_benchmark.videomme.schema import CATALOG_DIR, apply_schema

ALLOWED_PATHS = frozenset({'1', '1L', '2', '3', '5'})
DEFAULT_PATHS = frozenset({'1', '2'})

# path -> (letter, correct, cost, response column); Path 3 is local, its raw text is the call.
PATH_COLUMNS = {
    '1': ('native_letter', 'native_correct', 'native_cost', 'native_response'),
    '1L': ('native_low_letter', 'native_low_correct', 'native_low_cost', 'native_low_response'),
    '2': ('orch_letter', 'orch_correct', 'orch_cost', 'orch_response'),
    '3': ('oss_letter', 'oss_correct', None, 'oss_raw'),
    '5': ('nova_letter', 'nova_correct', 'nova_cost', 'nova_response'),
}
# path -> the per-video evidence cost (captions, transcript) its questions share
SHARED_COST = {'2': 'orch_shared_cost', '3': 'oss_shared_cost'}
# path -> a column that is None where the path did not run (Nova: video over the inline limit)
ATTEMPTED = {'5': 'nova_video'}
# path -> the answer call's token usage
USAGE = {'1': 'native_usage', '1L': 'native_low_usage', '2': 'orch_usage', '5': 'nova_usage'}
# Rows per insert. Each insert commits on its own, so an interrupted run keeps finished batches.
VIDEO_BATCH = 1
QUESTION_BATCH = 6


def field(path: str, name: str) -> str:
    """Prediction key for one path, e.g. field('1L', 'correct') == 'p1l_correct'.

    Pixeltable folds select aliases to lowercase and requires them to start with a letter.
    """
    return f'p{path.lower()}_{name}'


def parse_paths(raw: str | None) -> set[str]:
    return parse_path_spec(raw, allowed=ALLOWED_PATHS, default=DEFAULT_PATHS)


def videomme_config(config: BenchmarkConfig) -> BenchmarkConfig:
    """Video-MME defaults: 32 frames sampled and 24 kept (longer videos than the Pursuit clip),
    Nova Lite, unless VIDEOME_VISION_SAMPLE_KEYFRAMES, VIDEOME_FRAME_SELECT_BUDGET, or
    NOVA_MODEL_ID say otherwise.
    """
    return replace(
        config,
        vision_sample_keyframes=int(os.environ.get('VIDEOME_VISION_SAMPLE_KEYFRAMES', '32')),
        frame_select_budget=int(os.environ.get('VIDEOME_FRAME_SELECT_BUDGET', '24')),
        nova_model_id=os.environ.get('NOVA_MODEL_ID', 'amazon.nova-lite-v1:0'),
        # Path 3 shares the Gemini transcript here, isolating local vision and synthesis.
        oss_asr='gemini',
    )


def _local_downloads(assets_dir: Path) -> dict[str, str]:
    return {
        path.stem: str(path.resolve())
        for path in (assets_dir / 'videos').glob('*.mp4')
        if path.stat().st_size > 0
    }


def prepare_sample(
    *,
    n: int = DEFAULT_N,
    seed: int = DEFAULT_SEED,
    assets_dir: Path | None = None,
    reuse_manifest: bool = True,
    local_only: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """A duration-stratified sample of questions whose videos are on disk.

    local_only samples among already-downloaded videos (no network beyond cached annotations);
    otherwise candidate videos are downloaded first, so failed downloads cannot skew the
    short / medium / long quotas.
    """
    root = assets_dir or VIDEOME_ASSETS
    root.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest(root / 'sample_manifest.json') if reuse_manifest else None
    if (manifest and manifest.get('seed') == seed and manifest.get('n') == n
            and manifest.get('dataset_revision') == HF_REVISION):
        local = _local_downloads(root)
        questions = [q for q in manifest['questions'] if q['video_id'] in local]
        if len(questions) >= n:
            print(f'Reusing sample manifest: {n} questions', flush=True)
            return questions[:n], {q['video_id']: local[q['video_id']] for q in questions[:n]}

    print('Loading Video-MME annotations ...', flush=True)
    rows = load_videomme_rows()
    downloads = _local_downloads(root)
    if not local_only:
        wanted = unique_videos(sample_questions(rows, n=max(3 * n, 60), seed=seed))
        missing = [v for v in wanted if v['video_id'] not in downloads]
        if missing:
            print(f'Downloading {len(missing)} candidate videos ...', flush=True)
            downloads.update(download_videos(missing, assets_dir=root))
    eligible = [row for row in rows if row['video_id'] in downloads]
    questions = sample_questions(eligible, n=n, seed=seed)
    if len(questions) < n:
        raise RuntimeError(
            f'Only {len(questions)} of {n} questions have a downloaded video; '
            'lower --n or allow downloads.'
        )
    used = {q['video_id'] for q in questions}
    downloads = {vid: path for vid, path in downloads.items() if vid in used}
    save_manifest(questions, seed=seed, n=n, assets_dir=root, downloads=downloads)
    buckets = Counter(q['duration'] for q in questions)
    print(f'Sampled {len(questions)} questions from {len(used)} videos {dict(buckets)}', flush=True)
    return questions, downloads


def _table(name: str) -> pxt.Table:
    return pxt.get_table(f'{CATALOG_DIR}.{name}')


class InputConflict(ValueError):
    """An accepted ID has different inputs; resuming must never silently reuse its result."""


def _new_rows(name: str, key: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Check every input before either table inserts; identical IDs resume without calls."""
    tbl = _table(name)
    existing = {row[key]: row['input_sha256'] for row in tbl.select(
        getattr(tbl, key), tbl.input_sha256
    ).collect()}
    accepted: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row[key] in existing and existing[row[key]] is None:
            raise InputConflict(f'{name}.{key}={row[key]!r} has no saved input identity; '
                                'export before rebuilding the catalog.')
        identity = accepted.get(row[key], {}).get('input_sha256', existing.get(row[key]))
        if identity is not None and identity != row['input_sha256']:
            raise InputConflict(
                f'{name}.{key}={row[key]!r} has different inputs (annotation revision, '
                'media, or question). Use a new ID or export before rebuilding the catalog.'
            )
        accepted[row[key]] = row
    return [row for identity, row in accepted.items() if identity not in existing]


def _insert_new(name: str, key: str, rows: list[dict[str, Any]], batch: int) -> None:
    """Insert already preflighted rows, retrying failed cells once per committed batch."""
    tbl = _table(name)
    for start in range(0, len(rows), batch):
        chunk = rows[start : start + batch]
        print(
            f'Inserting {CATALOG_DIR}.{name} rows {start + 1}-{start + len(chunk)} '
            f'of {len(rows)} ...',
            flush=True,
        )
        status = tbl.insert(chunk, on_error='ignore')
        keys = [row[key] for row in chunk]
        for qualified in status.cols_with_excs or []:
            tbl_name, _, column = qualified.rpartition('.')
            target = _table(tbl_name.rsplit('/', 1)[-1])
            # Only this batch: earlier batches' failures were retried when they ran. A view
            # sees its base table's key column.
            failures = retry_column_once(target, column, getattr(target, key).isin(keys))
            if failures:
                print(f'Failed after retry: {qualified} ({failures} cells)', file=sys.stderr)


def run_videomme(
    config: BenchmarkConfig,
    paths: set[str],
    questions: list[dict[str, Any]],
    downloads: dict[str, str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Returns per-question predictions and per-video evidence records."""
    plan = plan_paths(config, paths)
    apply_schema(config, plan)
    videos = unique_videos(questions)
    media = {v['video_id']: media_identity(downloads[v['video_id']]) for v in videos}
    video_rows = [{
        'video_id': v['video_id'], 'video': downloads[v['video_id']],
        'media_sha256': media[v['video_id']]['sha256'],
        'media_bytes': media[v['video_id']]['bytes'], 'annotation_revision': HF_REVISION,
        'duration_bucket': v['duration'], 'domain': v['domain'], 'url': v['url'],
    } for v in videos]
    question_rows = [{
        'question_id': q['question_id'], 'video_id': q['video_id'],
        'video': downloads[q['video_id']], 'annotation_revision': HF_REVISION,
        'duration_bucket': q['duration'], 'domain': q['domain'], 'task_type': q['task_type'],
        'question': q['question'], 'options': q['options'], 'answer': q['answer'],
    } for q in questions]
    for row in video_rows + question_rows:
        # Equivalent paths to the same bytes have the same identity. Store the identity at
        # acceptance: rehashing the old path later cannot detect same-path replacement.
        row['input_sha256'] = input_identity({
            **{k: v for k, v in row.items() if k != 'video'},
            'media_sha256': media[row['video_id']]['sha256'],
        })
    new_videos = _new_rows('videos', 'video_id', video_rows)
    new_questions = _new_rows('questions', 'question_id', question_rows)
    _insert_new('videos', 'video_id', new_videos, VIDEO_BATCH)
    _insert_new('questions', 'question_id', new_questions, QUESTION_BATCH)
    evidence = collect_videos(plan, [v['video_id'] for v in videos], config.gemini_model)
    predictions = collect_predictions(plan, [q['question_id'] for q in questions], evidence, config)
    return predictions, evidence


def _list_cost(path: str, usage: dict | None, config: BenchmarkConfig) -> float | None:
    """The call priced without Gemini's implicit-cache discount."""
    if not usage:
        return None
    if path == '5':
        return nova_cost_impl(usage, config.nova_model_id)
    return gemini_cost_impl(uncached_usage_impl(usage), config.gemini_model)


def collect_predictions(
    plan: PathPlan,
    question_ids: list[str],
    videos: list[dict[str, Any]],
    config: BenchmarkConfig,
) -> list[dict[str, Any]]:
    """One record per question: per path its letter, correctness, cost, and failure message.

    `cost` is billed; `list_cost` prices the same tokens without the implicit-cache discount.
    An orchestrated path's cost includes its share of the video's evidence (captions and
    transcript), split evenly across that video's questions in the sample.
    """
    q = _table('questions')
    select: dict[str, Any] = {
        name: getattr(q, name)
        for name in ('question_id', 'video_id', 'duration_bucket', 'domain', 'task_type', 'answer',
                     'input_sha256', 'annotation_revision')
    }
    for path in plan.enabled():
        letter, correct, cost, call = PATH_COLUMNS[path]
        select[field(path, 'letter')] = getattr(q, letter)
        select[field(path, 'correct')] = getattr(q, correct)
        select[field(path, 'error')] = getattr(q, call).errormsg
        if cost:
            select[field(path, 'call_cost')] = getattr(q, cost)
            select[field(path, 'cost_error')] = getattr(q, cost).errormsg
        if path in SHARED_COST:
            select[field(path, 'video_shared_cost')] = getattr(q, SHARED_COST[path])
        if path in ATTEMPTED:
            select[field(path, 'attempted')] = getattr(q, ATTEMPTED[path]) != None  # noqa: E711
        if path in USAGE:
            select[field(path, 'usage')] = getattr(q, USAGE[path])
            select[field(path, 'usage_error')] = getattr(q, USAGE[path]).errormsg
    records = list(q.where(q.question_id.isin(question_ids)).select(**select).collect())
    by_video = {v['video_id']: v for v in videos}
    per_video = Counter(row['video_id'] for row in records)
    for row in records:
        vid = row['video_id']
        n = per_video[vid]
        row['duration_sec'] = by_video.get(vid, {}).get('duration_sec')
        for path in plan.enabled():
            row.pop(field(path, 'video_shared_cost'), None)
            shared_stages = ('caption', 'asr') if path == '2' else ('asr',) if path == '3' else ()
            shared = cost_totals(by_video[vid][f'{stage}_cost'] for stage in shared_stages)
            list_shared = cost_totals(
                by_video[vid][f'{stage}_list_cost'] for stage in shared_stages
            )
            call_cost = row.get(field(path, 'call_cost')) if path != '3' else 0.0
            shared_cost = shared.total / n if shared.total is not None else None
            row[field(path, 'shared_cost')] = shared_cost
            row[field(path, 'cost')] = cost_totals([call_cost, shared_cost]).total
            row[field(path, 'accounting_error')] = (
                row.get(field(path, 'usage_error')) or row.get(field(path, 'cost_error'))
                or ('Shared evidence cost is unknown' if shared.unknown else None)
            )
            list_call = (
                _list_cost(path, row.get(field(path, 'usage')), config) if path != '3' else 0.0
            )
            row[field(path, 'list_cost')] = cost_totals([
                list_call, list_shared.total / n if list_shared.total is not None else None
            ]).total
            row[field(path, 'response_accounted_cost')] = (
                cost_totals([call_cost]).known + sum(
                    by_video[vid][f'{stage}_response_accounted_cost'] for stage in shared_stages
                ) / n
            )
            row[field(path, 'response_accounted_list_cost')] = (
                cost_totals([list_call]).known + sum(
                    by_video[vid][f'{stage}_response_accounted_list_cost']
                    for stage in shared_stages
                ) / n
            )
    return sorted(records, key=lambda row: row['question_id'])


def collect_videos(plan: PathPlan, video_ids: list[str], model: str) -> list[dict[str, Any]]:
    """One record per video: its duration and, for the orchestrated paths, the billed and list
    cost and token usage of the evidence it shares across its questions (captions, transcript).
    """
    v = _table('videos')
    rows = v.where(v.video_id.isin(video_ids)).select(
        v.video_id, v.duration_bucket, v.duration_sec, v.input_sha256, v.annotation_revision,
        v.media_sha256, v.media_bytes,
    )
    records = {row['video_id']: dict(row) for row in rows.collect()}
    for rec in records.values():
        rec['media_identity'] = {'sha256': rec.pop('media_sha256'), 'bytes': rec.pop('media_bytes')}
    stages = []
    if plan.modular:
        ac = _table('audio_chunks')
        stages.append(('asr', ac, ac.gemini_asr_cost, ac.gemini_asr_usage, ac.gemini_transcript))
    if plan.orchestrated:
        kf = _table('keyframes')
        stages.append(
            ('caption', kf, kf.gemini_caption_cost, kf.gemini_caption_usage, kf.gemini_caption)
        )
    for stage, tbl, cost, usage, text in stages:
        for rec in records.values():
            rec.update(
                {f'{stage}_{k}': 0 for k in ('calls', 'failed', 'empty', 'unknown_cost')}
                | {f'{stage}_response_accounted_cost': 0.0,
                   f'{stage}_response_accounted_list_cost': 0.0,
                   f'{stage}_unknown_list_cost': 0}
            )
            rec[f'{stage}_usage'] = {}
        response = getattr(tbl, f'gemini_{"caption" if stage == "caption" else "asr"}_response')
        selected = tbl.where(tbl.video_id.isin(video_ids)).select(
            tbl.video_id, cost=cost, usage=usage, text=text,
            error=response.errormsg,
        )
        for row in selected.collect():
            rec = records[row['video_id']]
            rec[f'{stage}_calls'] += 1
            rec[f'{stage}_failed'] += bool(row['error'])
            costs = cost_totals([row['cost']])
            listed = cost_totals([gemini_cost_impl(uncached_usage_impl(row['usage']), model)
                                 if row['usage'] else None])
            rec[f'{stage}_unknown_cost'] += costs.unknown
            rec[f'{stage}_unknown_list_cost'] += listed.unknown
            # Billed but no text: a recitation or safety stop, which raises no error.
            rec[f'{stage}_empty'] += row['cost'] is not None and not row['text']
            rec[f'{stage}_response_accounted_cost'] += costs.known
            rec[f'{stage}_response_accounted_list_cost'] += listed.known
            add_usage(rec[f'{stage}_usage'], row['usage'])
        for rec in records.values():
            rec[f'{stage}_cost'] = (None if rec[f'{stage}_unknown_cost'] else
                                   rec[f'{stage}_response_accounted_cost'])
            rec[f'{stage}_list_cost'] = (None if rec[f'{stage}_unknown_list_cost'] else
                                        rec[f'{stage}_response_accounted_list_cost'])
    return sorted(records.values(), key=lambda rec: rec['video_id'])
