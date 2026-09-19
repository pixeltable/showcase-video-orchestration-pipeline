"""Tests for batched Gemini vision helpers."""

from video_benchmark.gemini_batch import _batch_prompt, _parse_batch_response


def test_batch_prompt_lists_positions():
    text = _batch_prompt('What happens?', [1.0, 42.5])
    assert 'What happens?' in text
    assert '[1.0s]' in text
    assert '[42.5s]' in text


def test_parse_batch_response_splits_by_timestamp():
    positions = [0.0, 10.0, 20.0]
    raw = (
        '[0.0s] Opening scene in an office.\n\n'
        '[10.0s] Two people talking at a table.\n\n'
        '[20.0s] Elevator doors close.'
    )
    parts = _parse_batch_response(raw, positions)
    assert len(parts) == 3
    assert 'office' in parts[0]
    assert 'table' in parts[1]
    assert 'Elevator' in parts[2]


def test_parse_batch_response_single_position():
    assert _parse_batch_response('One caption only.', [5.0]) == ['One caption only.']
