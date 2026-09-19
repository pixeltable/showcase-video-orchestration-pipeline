"""Stratified Video-MME question sampling (annotations only)."""

from __future__ import annotations

import json
import random
from collections import defaultdict
from pathlib import Path
from typing import Any

from video_benchmark.videomme import DEFAULT_N, DEFAULT_SEED, MANIFEST_NAME, VIDEOME_ASSETS

DURATION_BUCKETS = ('short', 'medium', 'long')
HF_DATASET = 'lmms-lab/Video-MME'
HF_CONFIG = 'videomme'


def _row_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    options = row.get('options')
    if options is not None and not isinstance(options, list):
        options = list(options)
    return {
        'video_id': str(row['video_id']),
        'duration': str(row['duration']).strip().lower(),
        'domain': str(row.get('domain') or ''),
        'sub_category': str(row.get('sub_category') or ''),
        'url': str(row['url']),
        'videoID': str(row.get('videoID') or ''),
        'question_id': str(row['question_id']),
        'task_type': str(row.get('task_type') or ''),
        'question': str(row['question']),
        'options': options or [],
        'answer': str(row['answer']).strip().upper()[:1],
    }


def load_videomme_rows() -> list[dict[str, Any]]:
    """Load full Video-MME annotation split from Hugging Face."""
    from datasets import load_dataset

    ds = load_dataset(HF_DATASET, HF_CONFIG, split='test')
    return [_row_to_dict(dict(row)) for row in ds]


def _quota_per_bucket(n: int) -> dict[str, int]:
    base, rem = divmod(n, len(DURATION_BUCKETS))
    quotas = {b: base for b in DURATION_BUCKETS}
    for i, b in enumerate(DURATION_BUCKETS):
        if i < rem:
            quotas[b] += 1
    return quotas


def sample_questions(
    rows: list[dict[str, Any]],
    *,
    n: int = DEFAULT_N,
    seed: int = DEFAULT_SEED,
    exclude_video_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """
    Stratify by duration; prefer videos that contribute multiple questions
    so Path 2 shared prep amortizes across ~n/3 unique videos.
    """
    exclude = exclude_video_ids or set()
    rng = random.Random(seed)
    quotas = _quota_per_bucket(n)

    by_duration: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        dur = row['duration']
        if dur not in quotas:
            continue
        if row['video_id'] in exclude:
            continue
        by_duration[dur].append(row)

    selected: list[dict[str, Any]] = []
    for dur, need in quotas.items():
        pool = list(by_duration.get(dur, []))
        if not pool:
            continue
        by_video: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in pool:
            by_video[row['video_id']].append(row)
        video_ids = list(by_video.keys())
        rng.shuffle(video_ids)
        # Prefer videos with more questions first (stable within shuffle via secondary sort).
        video_ids.sort(key=lambda vid: -len(by_video[vid]))
        picked: list[dict[str, Any]] = []
        for vid in video_ids:
            if len(picked) >= need:
                break
            qs = list(by_video[vid])
            rng.shuffle(qs)
            for q in qs:
                if len(picked) >= need:
                    break
                picked.append(q)
        # If still short, fill from remaining pool randomly.
        if len(picked) < need:
            picked_ids = {p['question_id'] for p in picked}
            remaining = [r for r in pool if r['question_id'] not in picked_ids]
            rng.shuffle(remaining)
            picked.extend(remaining[: need - len(picked)])
        selected.extend(picked[:need])

    # Global trim / pad if some buckets were empty.
    if len(selected) < n:
        used = {r['question_id'] for r in selected}
        leftover = [
            r
            for r in rows
            if r['question_id'] not in used and r['video_id'] not in exclude
        ]
        rng.shuffle(leftover)
        selected.extend(leftover[: n - len(selected)])
    return selected[:n]


def unique_videos(questions: list[dict[str, Any]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for q in questions:
        vid = q['video_id']
        if vid in seen:
            continue
        seen.add(vid)
        out.append(
            {
                'video_id': vid,
                'url': q['url'],
                'videoID': q.get('videoID') or '',
                'duration': q['duration'],
                'domain': q.get('domain') or '',
            }
        )
    return out


def manifest_path(assets_dir: Path | None = None) -> Path:
    return (assets_dir or VIDEOME_ASSETS) / MANIFEST_NAME


def save_manifest(
    questions: list[dict[str, Any]],
    *,
    seed: int,
    n: int,
    assets_dir: Path | None = None,
    downloads: dict[str, str] | None = None,
) -> Path:
    root = assets_dir or VIDEOME_ASSETS
    root.mkdir(parents=True, exist_ok=True)
    path = manifest_path(root)
    payload = {
        'seed': seed,
        'n': n,
        'dataset': HF_DATASET,
        'config': HF_CONFIG,
        'questions': questions,
        'videos': unique_videos(questions),
        'downloads': downloads or {},
    }
    path.write_text(json.dumps(payload, indent=2))
    return path


def load_manifest(path: Path | None = None) -> dict[str, Any] | None:
    p = path or manifest_path()
    if not p.exists():
        return None
    return json.loads(p.read_text())
