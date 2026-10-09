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

from video_benchmark.config import BenchmarkConfig
from video_benchmark.paths import parse_paths as parse_path_spec
from video_benchmark.pricing import gemini_cost_impl, nova_cost_impl, uncached_usage_impl
from video_benchmark.provenance import media_identity
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


def _insert_new(name: str, key: str, rows: list[dict[str, Any]], batch: int) -> None:
    """Insert rows whose key is not in the table yet, `batch` at a time, retrying each failed
    cell of the batch once."""
    tbl = _table(name)
    existing = {row[key] for row in tbl.select(getattr(tbl, key)).collect()}
    new_rows = [row for row in rows if row[key] not in existing]
    for start in range(0, len(new_rows), batch):
        chunk = new_rows[start : start + batch]
        print(
            f'Inserting {CATALOG_DIR}.{name} rows {start + 1}-{start + len(chunk)} '
            f'of {len(new_rows)} ...',
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
    _insert_new(
        'videos',
        'video_id',
        [
            {
                'video_id': v['video_id'],
                'video': downloads[v['video_id']],
                'duration_bucket': v['duration'],
                'domain': v['domain'],
                'url': v['url'],
            }
            for v in videos
        ],
        VIDEO_BATCH,
    )
    _insert_new(
        'questions',
        'question_id',
        [
            {
                'question_id': q['question_id'],
                'video_id': q['video_id'],
                'video': downloads[q['video_id']],
                'duration_bucket': q['duration'],
                'domain': q['domain'],
                'task_type': q['task_type'],
                'question': q['question'],
                'options': q['options'],
                'answer': q['answer'],
            }
            for q in questions
        ],
        QUESTION_BATCH,
    )
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
        for name in ('question_id', 'video_id', 'duration_bucket', 'domain', 'task_type', 'answer')
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
    shared_list = {
        vid: {
            '2': v.get('caption_list_cost', 0.0) + v.get('asr_list_cost', 0.0),
            '3': v.get('asr_list_cost', 0.0),
        }
        for vid, v in by_video.items()
    }
    per_video = Counter(row['video_id'] for row in records)
    for row in records:
        vid = row['video_id']
        n = per_video[vid]
        row['duration_sec'] = by_video.get(vid, {}).get('duration_sec')
        for path in plan.enabled():
            shared = (row.pop(field(path, 'video_shared_cost'), None) or 0.0) / n
            shared_stages = ('caption', 'asr') if path == '2' else ('asr',) if path == '3' else ()
            shared_known = all(
                not by_video[vid].get(f'{stage}_unknown_cost', 0) for stage in shared_stages
            )
            call_cost = row.get(field(path, 'call_cost')) if path != '3' else 0.0
            row[field(path, 'shared_cost')] = shared if shared_known else None
            row[field(path, 'cost')] = (
                call_cost + shared if call_cost is not None and shared_known else None
            )
            row[field(path, 'accounting_error')] = (
                row.get(field(path, 'usage_error')) or row.get(field(path, 'cost_error'))
                or ('Shared evidence cost is unknown' if not shared_known else None)
            )
            list_shared = (
                shared_list.get(vid, {}).get(path, 0.0) / n if path in SHARED_COST else 0.0
            )
            list_call = (
                _list_cost(path, row.get(field(path, 'usage')), config) if path != '3' else 0.0
            )
            row[field(path, 'list_cost')] = (
                list_call + list_shared if list_call is not None and shared_known else None
            )
    return sorted(records, key=lambda row: row['question_id'])


def collect_videos(plan: PathPlan, video_ids: list[str], model: str) -> list[dict[str, Any]]:
    """One record per video: its duration and, for the orchestrated paths, the billed and list
    cost and token usage of the evidence it shares across its questions (captions, transcript).
    """
    v = _table('videos')
    rows = v.where(v.video_id.isin(video_ids)).select(
        v.video_id, v.duration_bucket, v.duration_sec, media_path=v.video.localpath
    )
    records = {row['video_id']: dict(row) for row in rows.collect()}
    for rec in records.values():
        rec['media_identity'] = media_identity(rec.pop('media_path'))
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
                | {f'{stage}_cost': 0.0}
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
            rec[f'{stage}_unknown_cost'] += row['cost'] is None
            # Billed but no text: a recitation or safety stop, which raises no error.
            rec[f'{stage}_empty'] += row['cost'] is not None and not row['text']
            rec[f'{stage}_cost'] += row['cost'] or 0.0
            add_usage(rec[f'{stage}_usage'], row['usage'])
        for rec in records.values():
            # Cost is linear in token counts, so pricing the summed usage prices every call.
            usage = uncached_usage_impl(rec[f'{stage}_usage'])
            rec[f'{stage}_list_cost'] = gemini_cost_impl(usage, model) if usage else 0.0
    return sorted(records.values(), key=lambda rec: rec['video_id'])
