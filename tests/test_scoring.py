"""Pursuit answer heuristics."""

from __future__ import annotations

from video_benchmark.scoring import CLIP_CHECKS, GENERAL_CHECKS, score_answer


def test_clip_checks():
    text = (
        'Chris tells Jay he must have had on some really nice pants; the internship pays no salary.'
    )
    scores = score_answer(text)
    assert all(scores[c] for c in ('nice_pants', 'jay', 'chris', 'salary'))
    assert not scores['tonight']
    assert score_answer('It is an unpaid internship.')['salary']
    assert not score_answer('It is unpaid.')['salary']
    assert set(scores) == set(CLIP_CHECKS) | set(GENERAL_CHECKS)


def test_general_checks():
    body = ' '.join(['word'] * 210)
    complete = score_answer(f'**Main Activities:** x. **Speakers:** y. **Visual Events:** {body}.')
    assert complete['complete'] and complete['sections'] and not complete['truncated']
    cut = score_answer(' '.join(['word'] * 60) + ' and then')
    assert cut['truncated'] and not cut['complete']
    assert score_answer('toneeeeee')['truncated']
    spam = score_answer('At 1s a man. At 2s a man. At 3.5 seconds a man.')
    assert not spam['no_spam']
