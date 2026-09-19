"""Unit tests for Video-MME sampling, letter extract, cost amortization."""

from __future__ import annotations

from video_benchmark.videomme.sample import sample_questions, unique_videos
from video_benchmark.videomme.scoring import (
    amortize_shared_cost,
    extract_letter,
    format_options,
    is_correct,
    mcq_prompt,
    summarize_scores,
)


def _fake_rows() -> list[dict]:
    rows = []
    for dur_i, dur in enumerate(('short', 'medium', 'long')):
        for v in range(4):
            vid = f'{dur[0]}{v:02d}'
            for q in range(3):
                rows.append(
                    {
                        'video_id': vid,
                        'duration': dur,
                        'domain': 'Knowledge',
                        'sub_category': 'x',
                        'url': f'https://youtube.com/watch?v={vid}',
                        'videoID': vid,
                        'question_id': f'{vid}-q{q}',
                        'task_type': 'OCR',
                        'question': f'Q {vid} {q}?',
                        'options': ['A. a', 'B. b', 'C. c', 'D. d'],
                        'answer': 'A',
                    }
                )
    return rows


def test_extract_letter_answer_line():
    assert extract_letter('Because reasons.\nAnswer: C') == 'C'
    assert extract_letter('Final answer: d') == 'D'
    assert extract_letter(r'The choice is \boxed{B}') == 'B'
    assert extract_letter('I conclude the answer is A.') == 'A'
    assert extract_letter('Answer: None') is None


def test_extract_letter_last_line():
    assert extract_letter('I think the choice is\nB') == 'B'


def test_window_shared_context_long():
    from video_benchmark.videomme.scoring import window_shared_context

    big = 'HEAD' + ('x' * 80_000) + 'MID' + ('y' * 80_000) + 'TAIL'
    out = window_shared_context(big, video_duration_sec=2000.0, max_chars=10_000)
    assert 'HEAD' in out
    assert 'TAIL' in out
    assert 'mid window' in out
    assert len(out) < len(big)


def test_is_correct():
    assert is_correct('a', 'A')
    assert not is_correct('B', 'A')
    assert not is_correct(None, 'A')


def test_sample_stratified_counts():
    rows = _fake_rows()
    picked = sample_questions(rows, n=30, seed=7)
    assert len(picked) == 30
    by_dur = {}
    for r in picked:
        by_dur[r['duration']] = by_dur.get(r['duration'], 0) + 1
    assert by_dur.get('short') == 10
    assert by_dur.get('medium') == 10
    assert by_dur.get('long') == 10
    # Prefer multi-Q videos → unique videos should be well under 30
    assert len(unique_videos(picked)) <= 15


def test_sample_deterministic():
    rows = _fake_rows()
    a = sample_questions(rows, n=12, seed=99)
    b = sample_questions(rows, n=12, seed=99)
    assert [x['question_id'] for x in a] == [x['question_id'] for x in b]


def test_amortize_shared_cost():
    preds = [
        {'video_id': 'v1', 'orchestrated_synth_cost': 0.01},
        {'video_id': 'v1', 'orchestrated_synth_cost': 0.02},
        {'video_id': 'v2', 'orchestrated_synth_cost': 0.03},
    ]
    out = amortize_shared_cost(preds, {'v1': 0.10, 'v2': 0.05})
    assert abs(out[0]['orchestrated_shared_amortized'] - 0.05) < 1e-9
    assert abs(out[0]['orchestrated_total_cost'] - 0.06) < 1e-9
    assert abs(out[2]['orchestrated_total_cost'] - 0.08) < 1e-9


def test_summarize_scores():
    preds = [
        {
            'video_id': 'v1',
            'duration': 'short',
            'native_correct': True,
            'orchestrated_correct': False,
            'native_cost': 0.1,
            'orchestrated_total_cost': 0.05,
        },
        {
            'video_id': 'v1',
            'duration': 'short',
            'native_correct': True,
            'orchestrated_correct': True,
            'native_cost': 0.1,
            'orchestrated_total_cost': 0.05,
        },
    ]
    s = summarize_scores(preds)
    assert s['native_accuracy'] == 1.0
    assert s['orchestrated_accuracy'] == 0.5
    assert abs(s['native_cost_per_correct'] - 0.1) < 1e-9
    assert abs(s['orchestrated_cost_per_correct'] - 0.1) < 1e-9


def test_mcq_prompt_includes_answer_format():
    text = mcq_prompt('What color?', ['A. Red', 'B. Blue', 'C. Green', 'D. Yellow'])
    assert 'Answer: X' in text
    assert 'What color?' in text
    assert format_options(['Red', 'Blue']) == 'A. Red\nB. Blue'
