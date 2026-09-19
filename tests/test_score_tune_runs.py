"""Tests for native-parity scoring heuristics."""

from video_benchmark.scoring import score_insight_text


def test_score_insight_text_detects_key_signals():
    text = (
        '**Main Activities:** interview. **Speakers:** Jay. **Visual Events:** 0:00-1:00. '
        'Chris Gardner interviews with Jay. He must have had on some really nice pants. '
        'There is no salary. Jay says Tonight. ' + ('word ' * 220) + 'Done.'
    )
    scores = score_insight_text(text)
    assert scores['nice_pants'] is True
    assert scores['jay_named'] is True
    assert scores['chris_named'] is True
    assert scores['has_salary'] is True
    assert scores['has_tonight'] is True
    assert scores['complete'] is True
    assert scores['truncated'] is False
    assert scores['has_sections'] is True
    assert scores['no_per_frame_spam'] is True


def test_score_insight_text_flags_incomplete_and_spam():
    text = 'At 43.3 seconds something. At 10.0 seconds again. At 20.0 seconds more. short tone'
    scores = score_insight_text(text)
    assert scores['complete'] is False
    assert scores['no_per_frame_spam'] is False
    assert scores['nice_pants'] is False


def test_has_salary_rejects_bare_unpaid():
    text = 'He has unpaid parking tickets. ' + ('word ' * 220)
    scores = score_insight_text(text)
    assert scores['has_salary'] is False


def test_has_salary_accepts_unpaid_internship():
    text = 'It is an unpaid internship. ' + ('word ' * 220)
    scores = score_insight_text(text)
    assert scores['has_salary'] is True


def test_truncated_trailing_junk():
    text = ('word ' * 50) + 'toneeeee'
    scores = score_insight_text(text)
    assert scores['truncated'] is True
