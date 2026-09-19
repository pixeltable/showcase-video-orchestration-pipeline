"""MCQ letter extraction, exact-match scoring, multi-path cost amortization."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

_ANSWER_LINE = re.compile(
    r'(?:^|\n)\s*(?:final\s+)?answer\s*[:\-]\s*([A-D])\b',
    re.IGNORECASE,
)
_BOXED = re.compile(r'\\boxed\{\s*([A-D])\s*\}', re.IGNORECASE)
_THE_ANSWER_IS = re.compile(
    r'(?:the\s+)?(?:correct\s+)?answer\s+is\s*[:\-]?\s*([A-D])\b',
    re.IGNORECASE,
)
_BARE_LETTER = re.compile(r'\b([A-D])\b')

# Long-video ASR windowing for synth (seconds)
LONG_VIDEO_ASR_SEC = 900.0  # 15 min


def extract_letter(text: str | None) -> str | None:
    """Extract A–D from model output; prefer explicit Answer / boxed forms."""
    if not text or not str(text).strip():
        return None
    raw = str(text).strip()
    # Explicit "Answer: None" / missing → no letter
    if re.search(r'(?:^|\n)\s*(?:final\s+)?answer\s*[:\-]\s*none\b', raw, re.I):
        return None
    for pattern in (_ANSWER_LINE, _BOXED, _THE_ANSWER_IS):
        matches = list(pattern.finditer(raw))
        if matches:
            return matches[-1].group(1).upper()
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    if not lines:
        return None
    last = lines[-1]
    letters = _BARE_LETTER.findall(last)
    if len(letters) == 1:
        return letters[0].upper()
    if letters:
        return letters[-1].upper()
    return None


def is_correct(pred: str | None, gold: str | None) -> bool:
    if not pred or not gold:
        return False
    return pred.strip().upper()[:1] == gold.strip().upper()[:1]


def format_options(options: list[str] | None) -> str:
    if not options:
        return ''
    lines: list[str] = []
    for i, opt in enumerate(options):
        letter = chr(ord('A') + i)
        text = str(opt).strip()
        if re.match(r'^[A-D][.):]\s*', text, re.IGNORECASE):
            lines.append(text)
        else:
            lines.append(f'{letter}. {text}')
    return '\n'.join(lines)


def mcq_prompt(question: str, options: list[str] | None) -> str:
    opts = format_options(options)
    return (
        'Watch the video (or use the provided evidence) and answer the multiple-choice '
        'question. Choose exactly one of A, B, C, or D.\n\n'
        f'Question: {question.strip()}\n\n'
        f'Options:\n{opts}\n\n'
        'Reason briefly if needed, then end with a single line exactly in this format:\n'
        'Answer: X'
    )


def mcq_frame_prompt(position_sec: float | None = None) -> str:
    time_anchor = ''
    if position_sec is not None:
        time_anchor = f'This keyframe is at {float(position_sec):.1f}s. '
    return (
        f'{time_anchor}'
        'Describe this keyframe in 2-3 sentences for later multiple-choice answering: '
        'who is visible, what they are doing, the setting, any on-screen text, '
        'and notable actions. '
        'Describe only what is visible.'
    )


def truncate_context(ctx: str, max_chars: int = 100_000) -> str:
    if len(ctx) <= max_chars:
        return ctx
    half = max_chars // 2
    return ctx[:half] + '\n\n...[truncated]...\n\n' + ctx[-half:]


def window_shared_context(
    ctx: str,
    *,
    video_duration_sec: float | None,
    long_threshold_sec: float = LONG_VIDEO_ASR_SEC,
    max_chars: int = 100_000,
) -> str:
    """
    For long videos, prefer a middle+tail window of evidence rather than only
    head+tail of a mega transcript (helps late-video questions).
    """
    if not ctx:
        return ctx
    dur = float(video_duration_sec or 0.0)
    if dur < long_threshold_sec or len(ctx) <= max_chars:
        return truncate_context(ctx, max_chars)
    # Keep first ~20%, middle ~40%, last ~40% of the string budget
    budget = max_chars
    head_n = int(budget * 0.20)
    mid_n = int(budget * 0.40)
    tail_n = budget - head_n - mid_n
    mid_start = max(0, (len(ctx) - mid_n) // 2)
    parts = [
        ctx[:head_n],
        '\n\n...[mid window]...\n\n',
        ctx[mid_start : mid_start + mid_n],
        '\n\n...[tail]...\n\n',
        ctx[-tail_n:],
    ]
    return ''.join(parts)


def amortize_shared_cost(
    predictions: list[dict[str, Any]],
    video_shared_costs: dict[str, float],
    *,
    synth_key: str = 'orchestrated_synth_cost',
    shared_out_key: str = 'orchestrated_shared_amortized',
    total_out_key: str = 'orchestrated_total_cost',
) -> list[dict[str, Any]]:
    """Attach total = shared_cost/n_questions_on_video + synthesis_cost."""
    counts: dict[str, int] = defaultdict(int)
    for p in predictions:
        counts[p['video_id']] += 1
    out: list[dict[str, Any]] = []
    for p in predictions:
        row = dict(p)
        vid = row['video_id']
        shared = float(video_shared_costs.get(vid, 0.0))
        n = max(counts[vid], 1)
        synth = float(row.get(synth_key) or 0.0)
        row[shared_out_key] = shared / n
        row[total_out_key] = shared / n + synth
        out.append(row)
    return out


def summarize_scores(predictions: list[dict[str, Any]]) -> dict[str, Any]:
    def _acc(rows: list[dict[str, Any]], key: str) -> float | None:
        scored = [r for r in rows if r.get(key) is not None]
        if not scored:
            return None
        hits = sum(1 for r in scored if r.get(key))
        return hits / len(scored)

    def _path_block(
        correct_key: str, cost_key: str, ingest_key: str | None = None
    ) -> dict[str, Any]:
        scored = [r for r in predictions if r.get(correct_key) is not None]
        n_ok = sum(1 for r in scored if r.get(correct_key))
        total_cost = sum(float(r.get(cost_key) or 0.0) for r in scored)
        block: dict[str, Any] = {
            'n': len(scored),
            'correct': n_ok,
            'accuracy': (n_ok / len(scored)) if scored else None,
            'total_cost': total_cost,
            'cost_per_correct': (total_cost / n_ok) if n_ok else None,
        }
        if ingest_key:
            block['ingest_failed'] = sum(1 for r in predictions if r.get(ingest_key))
        return block

    native_cost = sum(float(r.get('native_cost') or 0.0) for r in predictions)
    orch_cost = sum(float(r.get('orchestrated_total_cost') or 0.0) for r in predictions)
    n_native_ok = sum(1 for r in predictions if r.get('native_correct'))
    n_orch_ok = sum(1 for r in predictions if r.get('orchestrated_correct'))
    n = len(predictions)

    by_duration: dict[str, dict[str, Any]] = {}
    for dur in ('short', 'medium', 'long'):
        subset = [r for r in predictions if r.get('duration') == dur]
        by_duration[dur] = {
            'n': len(subset),
            'native_acc': _acc(subset, 'native_correct'),
            'orchestrated_acc': _acc(subset, 'orchestrated_correct'),
            'oss_acc': _acc(subset, 'oss_correct'),
            'nova_acc': _acc(subset, 'nova_correct'),
        }

    summary: dict[str, Any] = {
        'n': n,
        'native_accuracy': _acc(predictions, 'native_correct'),
        'orchestrated_accuracy': _acc(predictions, 'orchestrated_correct'),
        'oss_accuracy': _acc(predictions, 'oss_correct'),
        'nova_accuracy': _acc(predictions, 'nova_correct'),
        'native_correct': n_native_ok,
        'orchestrated_correct': n_orch_ok,
        'oss_correct': sum(1 for r in predictions if r.get('oss_correct')),
        'nova_correct': sum(1 for r in predictions if r.get('nova_correct')),
        'native_total_cost': native_cost,
        'orchestrated_total_cost': orch_cost,
        'oss_total_cost': sum(float(r.get('oss_total_cost') or 0.0) for r in predictions),
        'nova_total_cost': sum(float(r.get('nova_cost') or 0.0) for r in predictions),
        'native_cost_per_correct': (native_cost / n_native_ok) if n_native_ok else None,
        'orchestrated_cost_per_correct': (orch_cost / n_orch_ok) if n_orch_ok else None,
        'oss_cost_per_correct': None,
        'nova_cost_per_correct': None,
        'native_ingest_failed': sum(1 for r in predictions if r.get('native_ingest_failed')),
        'nova_ingest_failed': sum(1 for r in predictions if r.get('nova_ingest_failed')),
        'by_duration': by_duration,
        'paths': {
            'native': _path_block('native_correct', 'native_cost', 'native_ingest_failed'),
            'orchestrated': _path_block('orchestrated_correct', 'orchestrated_total_cost'),
            'oss': _path_block('oss_correct', 'oss_total_cost'),
            'nova': _path_block('nova_correct', 'nova_cost', 'nova_ingest_failed'),
        },
        'path3_asr_note': 'shared Gemini ASR (not WhisperX) for this Video-MME slice',
    }
    n_oss_ok = summary['oss_correct']
    n_nova_ok = summary['nova_correct']
    if n_oss_ok:
        summary['oss_cost_per_correct'] = summary['oss_total_cost'] / n_oss_ok
    if n_nova_ok:
        summary['nova_cost_per_correct'] = summary['nova_total_cost'] / n_nova_ok
    return summary
