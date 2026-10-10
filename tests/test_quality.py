"""A completed model call and an empty transcript each require separate quality evidence."""

import pytest

from video_benchmark.evidence import (
    _parse_timestamp_sec,
    parse_diarized_transcript_impl,
    transcript_text_impl,
)
from video_benchmark.quality import check_cases, evaluate, labelled_cases


def test_recorded_hallucination_is_a_completed_incorrect_response():
    results = check_cases()
    actual = results[0]
    assert actual['completion'] == 'complete' and actual['correctness'] == 'fail'
    assert actual['findings'] == ['unsupported_speech', 'unsupported_transition']
    assert len(results) == 6 and all(len(case['case_sha256']) == 64 for case in results)


@pytest.mark.parametrize('stamp', ['nan', 'inf', '-1', '00:-01'])
def test_nonfinite_and_negative_timestamps_are_not_valid_evidence(stamp):
    assert _parse_timestamp_sec(stamp) is None
    lines = parse_diarized_transcript_impl(f'[{stamp}] Speaker 1: claimed speech')
    assert lines[0]['timestamp_status'] == 'invalid'
    assert 'claimed speech' not in transcript_text_impl(lines)


def test_refusal_and_missing_audio_do_not_claim_quality_or_silence():
    cases = {case['case_id']: evaluate(case) for case in labelled_cases()}
    assert cases['synthetic-refusal']['correctness'] == 'not_evaluated'
    assert cases['synthetic-missing-audio']['completion'] == 'not_called'
    assert 'speech status unknown' in transcript_text_impl([])
