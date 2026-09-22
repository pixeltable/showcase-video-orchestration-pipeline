"""Orchestrate Video-MME: sample → shared Path 2/3 → per-Q Paths 1,2,3,5."""

from __future__ import annotations

import os
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

from video_benchmark.config import BenchmarkConfig, load_config
from video_benchmark.paths import parse_paths as parse_path_spec
from video_benchmark.videomme import DEFAULT_N, DEFAULT_SEED, VIDEOME_ASSETS
from video_benchmark.videomme import pipeline as vm_pipeline
from video_benchmark.videomme.download import download_videos, video_file_path
from video_benchmark.videomme.infer import (
    native_mcq_answer,
    nova_mcq_answer,
    orchestrated_mcq_answer,
    oss_mcq_answer,
    score_prediction,
)
from video_benchmark.videomme.sample import (
    load_manifest,
    load_videomme_rows,
    sample_questions,
    save_manifest,
    unique_videos,
)
from video_benchmark.videomme.scoring import amortize_shared_cost, window_shared_context

ALLOWED_PATHS = frozenset({'1', '2', '3', '5'})
DEFAULT_PATHS = frozenset({'1', '2'})


def _recompute(vs, column: str) -> None:
    status = vs.recompute_columns(column, cascade=False)
    if status.num_excs:
        print(f'Recompute ({column}): {status.insert_msg()}', file=sys.stderr)


def parse_paths(raw: str | None) -> set[str]:
    return parse_path_spec(raw, allowed=ALLOWED_PATHS, default=DEFAULT_PATHS)


OSS_SYNTH_MAX_CHARS = 16_000


def apply_videomme_frame_defaults(config: BenchmarkConfig) -> BenchmarkConfig:
    """Bump Video-MME frame budgets unless a VIDEOME_* override is set.

    Pursuit VISION_SAMPLE_KEYFRAMES in .env.example must not block the bump.
    """
    sample_raw = os.environ.get('VIDEOME_VISION_SAMPLE_KEYFRAMES')
    select_raw = os.environ.get('VIDEOME_FRAME_SELECT_BUDGET')
    cap_raw = os.environ.get('VIDEOME_FRAME_CONTEXT_MAX_ENTRIES')
    return replace(
        config,
        vision_sample_keyframes=(
            int(sample_raw) if sample_raw else max(config.vision_sample_keyframes, 32)
        ),
        frame_select_budget=(
            int(select_raw) if select_raw else max(config.frame_select_budget, 24)
        ),
        frame_context_max_entries=(
            int(cap_raw) if cap_raw else max(config.frame_context_max_entries, 24)
        ),
    )


def manifest_is_reusable(existing: dict[str, Any] | None, *, n: int, seed: int) -> bool:
    if not existing or not existing.get('downloads'):
        return False
    if existing.get('seed') != seed or existing.get('n') != n:
        return False
    questions = existing.get('questions') or []
    return len(questions) >= n


def prepare_sample_and_downloads(
    *,
    n: int = DEFAULT_N,
    seed: int = DEFAULT_SEED,
    assets_dir: Path | None = None,
    reuse_manifest: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """
    Build a stratified sample with successful downloads.
    Download candidates first, then sample only from videos that landed on disk
    so short/medium/long quotas are preserved.
    """
    root = assets_dir or VIDEOME_ASSETS
    root.mkdir(parents=True, exist_ok=True)

    if reuse_manifest:
        existing = load_manifest(root / 'sample_manifest.json')
        if manifest_is_reusable(existing, n=n, seed=seed):
            downloads = {
                k: v
                for k, v in existing['downloads'].items()
                if Path(v).exists()
            }
            qs = [q for q in existing['questions'] if q['video_id'] in downloads]
            durs = {q.get('duration') for q in qs[:n]}
            stratified_ok = n < 3 or {'short', 'medium', 'long'} <= durs
            if len(qs) >= n and stratified_ok:
                print(
                    f'Reusing manifest with {len(qs[:n])} questions / '
                    f'{len({q["video_id"] for q in qs[:n]})} videos',
                    flush=True,
                )
                used = qs[:n]
                return used, {q['video_id']: downloads[q['video_id']] for q in used}

    print('Loading Video-MME annotations from Hugging Face...', flush=True)
    rows = load_videomme_rows()
    exclude: set[str] = set()
    downloads: dict[str, str] = {}
    questions: list[dict[str, Any]] = []

    for attempt in range(10):
        candidates = sample_questions(
            rows, n=max(n * 3, 60), seed=seed + attempt, exclude_video_ids=exclude
        )
        vids = [
            v
            for v in unique_videos(candidates)
            if v['video_id'] not in downloads and v['video_id'] not in exclude
        ]
        if vids:
            print(
                f'Download attempt {attempt + 1}: {len(vids)} candidate videos',
                flush=True,
            )
            got = download_videos(vids, assets_dir=root)
            downloads.update(got)
            exclude |= {v['video_id'] for v in vids if v['video_id'] not in got}

        ok_ids = set(downloads.keys())
        if not ok_ids:
            continue
        eligible = [r for r in rows if r['video_id'] in ok_ids]
        questions = sample_questions(eligible, n=n, seed=seed)
        if len(questions) >= n:
            break

    questions = questions[:n]
    if len(questions) < n:
        raise RuntimeError(
            f'Only obtained {len(questions)}/{n} questions after downloads; '
            f'check yt-dlp / YouTube availability.'
        )
    used_ids = {q['video_id'] for q in questions}
    downloads = {vid: path for vid, path in downloads.items() if vid in used_ids}
    save_manifest(questions, seed=seed, n=n, assets_dir=root, downloads=downloads)
    by_dur = {
        d: sum(1 for q in questions if q.get('duration') == d)
        for d in ('short', 'medium', 'long')
    }
    print(
        f'Sampled {len(questions)} Q across {len(downloads)} videos {by_dur}',
        flush=True,
    )
    return questions, downloads


def run_shared_path2(
    config: BenchmarkConfig,
    downloads: dict[str, str],
    video_meta: list[dict[str, str]],
    *,
    reset: bool = False,
) -> dict[str, dict[str, Any]]:
    """Insert videos and recompute shared Path 2 context/costs. Returns per-video dict."""
    if reset:
        vm_pipeline.reset_catalog()
        vm_pipeline.setup_pipeline(config)
    else:
        try:
            vm_pipeline.load_pipeline()
            if vm_pipeline.videos is None or vm_pipeline.videos.count() == 0:
                vm_pipeline.setup_pipeline(config)
        except Exception:  # noqa: BLE001
            vm_pipeline.setup_pipeline(config)
    vs = vm_pipeline.videos
    assert vs is not None

    existing = (
        set(vs.select(vs.video_id).collect().to_pandas()['video_id'].tolist())
        if vs.count()
        else set()
    )
    rows = []
    meta_by_id = {v['video_id']: v for v in video_meta}
    for vid, path in downloads.items():
        if vid in existing:
            continue
        m = meta_by_id.get(vid, {})
        rows.append(
            {
                'video_id': vid,
                'video': path,
                'duration': m.get('duration') or '',
                'domain': m.get('domain') or '',
                'url': m.get('url') or '',
            }
        )
    if rows:
        print(f'Inserting {len(rows)} videos into videomme.videos ...', flush=True)
        status = vs.insert(rows)
        if status.num_excs:
            print(f'Insert: {status.insert_msg()}', file=sys.stderr)

    df_check = vs.select(vs.video_id, vs.shared_context).collect().to_pandas()
    needs_recompute = df_check['shared_context'].isna().any() or (
        df_check['shared_context'].astype(str).str.len() < 20
    ).any()
    contaminated = vm_pipeline.parent_context_is_cross_contaminated(
        max_frames_per_video=int(config.vision_sample_keyframes or 24)
    )
    if contaminated:
        print(
            'Detected cross-video context bleed in parent rollups; '
            'rebuilding shared context from existing keyframes/ASR...',
            flush=True,
        )
        vm_pipeline.rebuild_parent_context(config)
        needs_recompute = False
    if needs_recompute:
        print(
            'Recomputing shared Path 2 (transcript + frames + context)...',
            flush=True,
        )
        for col in (
            'gemini_transcript_context',
            'gemini_asr_cost',
            'gemini_frame_context',
            'gemini_vision_track_cost',
            'gemini_frame_context_deduped',
        ):
            _recompute(vs, col)
        if config.scene_aware_frames:
            _recompute(vs, 'gemini_frame_context_selected')
        for col in (
            'gemini_frame_context_summarized',
            'shared_context',
            'gemini_asr_cost',
            'gemini_vision_track_cost',
        ):
            _recompute(vs, col)
    elif not contaminated:
        print('Reusing existing shared Path 2 context from catalog.', flush=True)

    df = (
        vs.select(
            vs.video_id,
            vs.shared_context,
            vs.video_duration_sec,
            vs.gemini_vision_track_cost,
            vs.gemini_asr_cost,
        )
        .collect()
        .to_pandas()
    )
    out: dict[str, dict[str, Any]] = {}
    for _, row in df.iterrows():
        vid = str(row['video_id'])
        vision = float(row['gemini_vision_track_cost'] or 0.0)
        asr = float(row['gemini_asr_cost'] or 0.0)
        out[vid] = {
            'shared_context': str(row['shared_context'] or ''),
            'video_duration_sec': float(row['video_duration_sec'] or 0.0),
            'shared_cost': vision + asr,
            'vision_cost': vision,
            'asr_cost': asr,
            'oss_shared_context': '',
            'oss_shared_cost': 0.0,
        }
    return out


def run_shared_path3(config: BenchmarkConfig, video_shared: dict[str, dict[str, Any]]) -> None:
    """Ensure OSS frame captions + oss_shared_context; mutate video_shared in place."""
    if vm_pipeline.oss_shared_ready():
        print('Reusing existing OSS shared context from catalog.', flush=True)
    else:
        print(
            'Computing OSS Path 3 shared frames (local VLM; may take a while)...',
            flush=True,
        )
        vm_pipeline.ensure_oss_shared(config)
    vs = vm_pipeline.videos
    assert vs is not None
    df = vs.select(vs.video_id, vs.oss_shared_context).collect().to_pandas()
    for _, row in df.iterrows():
        vid = str(row['video_id'])
        if vid in video_shared:
            video_shared[vid]['oss_shared_context'] = str(row['oss_shared_context'] or '')
            video_shared[vid]['oss_shared_cost'] = 0.0


def run_questions(
    config: BenchmarkConfig,
    questions: list[dict[str, Any]],
    downloads: dict[str, str],
    video_shared: dict[str, dict[str, Any]],
    *,
    paths: set[str] | None = None,
) -> list[dict[str, Any]]:
    active = set(paths) if paths is not None else set(DEFAULT_PATHS)
    predictions: list[dict[str, Any]] = []
    for i, q in enumerate(questions, start=1):
        vid = q['video_id']
        path = downloads[vid]
        shared = video_shared.get(vid) or {
            'shared_context': '',
            'oss_shared_context': '',
            'video_duration_sec': 0.0,
            'shared_cost': 0.0,
            'oss_shared_cost': 0.0,
        }
        dur = shared.get('video_duration_sec')
        print(
            f'[{i}/{len(questions)}] {q["question_id"]} video={vid} ({q.get("duration")}) '
            f'paths={sorted(active)}',
            flush=True,
        )
        ctx = window_shared_context(
            str(shared.get('shared_context') or ''),
            video_duration_sec=dur,
        )
        oss_raw_ctx = str(shared.get('oss_shared_context') or '')
        oss_ctx = window_shared_context(
            oss_raw_ctx,
            video_duration_sec=dur,
            max_chars=OSS_SYNTH_MAX_CHARS,
        )

        native_raw, native_letter, native_cost = '', None, 0.0
        orch_raw, orch_letter, orch_cost = '', None, 0.0
        oss_raw, oss_letter, oss_cost = None, None, 0.0
        nova_raw, nova_letter, nova_c = None, None, 0.0

        if '1' in active:
            try:
                native_raw, native_letter, native_cost = native_mcq_answer(
                    video_path=path,
                    question=q['question'],
                    options=list(q.get('options') or []),
                    model=config.gemini_model,
                )
            except Exception as exc:  # noqa: BLE001
                print(f'  native failed: {exc}', flush=True)
                native_raw, native_letter, native_cost = f'ERROR: {exc}', None, 0.0

        if '2' in active:
            try:
                orch_raw, orch_letter, orch_cost = orchestrated_mcq_answer(
                    shared_context=ctx,
                    question=q['question'],
                    options=list(q.get('options') or []),
                    model=config.gemini_model,
                    video_duration_sec=dur,
                )
            except Exception as exc:  # noqa: BLE001
                print(f'  orchestrated failed: {exc}', flush=True)
                orch_raw, orch_letter, orch_cost = f'ERROR: {exc}', None, 0.0

        if '3' in active and not oss_raw_ctx.strip():
            oss_raw, oss_letter, oss_cost = 'ERROR: missing oss_shared_context', None, 0.0
        elif '3' in active:
            try:
                oss_raw, oss_letter, oss_cost = oss_mcq_answer(
                    shared_context=oss_ctx,
                    question=q['question'],
                    options=list(q.get('options') or []),
                    synth_repo_id=config.oss_synth_repo_id,
                    synth_repo_filename=config.oss_synth_repo_filename,
                    synth_max_tokens=config.oss_synth_max_tokens,
                    video_duration_sec=dur,
                )
            except Exception as exc:  # noqa: BLE001
                print(f'  oss failed: {exc}', flush=True)
                oss_raw, oss_letter, oss_cost = f'ERROR: {exc}', None, 0.0

        if '5' in active and not config.enable_nova:
            nova_raw, nova_letter, nova_c = (
                'ERROR: Nova disabled (set ENABLE_NOVA=1 and AWS/Bedrock creds)',
                None,
                0.0,
            )
        elif '5' in active:
            try:
                nova_raw, nova_letter, nova_c = nova_mcq_answer(
                    video_path=path,
                    question=q['question'],
                    options=list(q.get('options') or []),
                    model_id=config.nova_model_id,
                    s3_uri='',
                    input_rate_per_m=config.nova_input_usd_per_1m,
                    output_rate_per_m=config.nova_output_usd_per_1m,
                )
            except Exception as exc:  # noqa: BLE001
                print(f'  nova failed: {exc}', flush=True)
                nova_raw, nova_letter, nova_c = f'ERROR: {exc}', None, 0.0

        pred = score_prediction(
            question_row=q,
            native_raw=native_raw,
            native_letter=native_letter,
            native_cost=native_cost,
            orch_raw=orch_raw,
            orch_letter=orch_letter,
            orch_synth_cost=orch_cost,
            oss_raw=oss_raw if '3' in active else None,
            oss_letter=oss_letter if '3' in active else None,
            oss_synth_cost=oss_cost,
            nova_raw=nova_raw if '5' in active else None,
            nova_letter=nova_letter if '5' in active else None,
            nova_cost=nova_c,
            run_native='1' in active,
            run_orch='2' in active,
        )
        predictions.append(pred)
        print(
            f'  gold={pred["gold"]} '
            f'n={native_letter} o={orch_letter} oss={oss_letter} nova={nova_letter} '
            f'ok=({pred["native_correct"]}, {pred["orchestrated_correct"]}, '
            f'{pred.get("oss_correct")}, {pred.get("nova_correct")})',
            flush=True,
        )

    shared_costs = {vid: float(v['shared_cost']) for vid, v in video_shared.items()}
    predictions = amortize_shared_cost(predictions, shared_costs)
    oss_shared = {vid: float(v.get('oss_shared_cost') or 0.0) for vid, v in video_shared.items()}
    predictions = amortize_shared_cost(
        predictions,
        oss_shared,
        synth_key='oss_synth_cost',
        shared_out_key='oss_shared_amortized',
        total_out_key='oss_total_cost',
    )
    return predictions


def run_videomme_dev(
    *,
    n: int = DEFAULT_N,
    seed: int = DEFAULT_SEED,
    reset: bool = False,
    reuse_manifest: bool = True,
    assets_dir: Path | None = None,
    config: BenchmarkConfig | None = None,
    paths: set[str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], BenchmarkConfig]:
    cfg = apply_videomme_frame_defaults(config or load_config())
    # Prefer Nova Lite for Video-MME unless user already set a model.
    if os.environ.get('NOVA_MODEL_ID') is None and 'nova-pro' in (cfg.nova_model_id or ''):
        cfg = replace(cfg, nova_model_id='amazon.nova-lite-v1:0')
    active = set(paths) if paths is not None else set(DEFAULT_PATHS)
    questions, downloads = prepare_sample_and_downloads(
        n=n, seed=seed, assets_dir=assets_dir, reuse_manifest=reuse_manifest
    )
    video_meta = unique_videos(questions)
    for v in video_meta:
        vid = v['video_id']
        if vid not in downloads:
            p = video_file_path(vid, assets_dir)
            if p.exists():
                downloads[vid] = str(p.resolve())
    if {'2', '3'} & active:
        video_shared = run_shared_path2(cfg, downloads, video_meta, reset=reset)
        if '3' in active:
            run_shared_path3(cfg, video_shared)
    else:
        video_shared = {
            vid: {
                'shared_context': '',
                'oss_shared_context': '',
                'video_duration_sec': 0.0,
                'shared_cost': 0.0,
                'oss_shared_cost': 0.0,
            }
            for vid in downloads
        }
    predictions = run_questions(cfg, questions, downloads, video_shared, paths=active)
    return predictions, video_shared, cfg
