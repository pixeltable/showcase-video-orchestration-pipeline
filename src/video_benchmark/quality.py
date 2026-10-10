"""Labelled quality boundaries; these diagnostics are not a general semantic evaluator."""

from __future__ import annotations

import json
import re
from pathlib import Path

from video_benchmark.evidence import _parse_timestamp_sec
from video_benchmark.provenance import input_identity, package_versions, source_identity
from video_benchmark.providers import gemini_text_impl


def evaluate(case: dict) -> dict:
    """Separate transport completion from correctness under explicit supplied labels."""
    response = case.get('response')
    text = gemini_text_impl(response) if isinstance(response, dict) else ''
    feedback = (response or {}).get('prompt_feedback') or (response or {}).get('promptFeedback')
    if case.get('error'):
        completion = 'error'
    elif feedback and (feedback.get('block_reason') or feedback.get('blockReason')):
        completion = 'refusal'
    elif response is None:
        completion = 'not_called'
    else:
        completion = 'complete' if text else 'empty'
    findings = []
    if not case.get('audio_present', True):
        findings.append('missing_audio')
    for stamp in re.findall(r'\[([^\]]+)\]', text):
        seconds = _parse_timestamp_sec(stamp)
        if seconds is None:
            findings.append('invalid_timestamp')
        elif not 0 <= seconds <= case['duration_sec']:
            findings.append('out_of_range_timestamp')
    labels = case.get('labels', {})
    if labels.get('speech_present') is False and re.search(
        r'\bSpeaker\s*\d+\b|\bsaying\b|\bspoken words\b', text, re.IGNORECASE
    ):
        findings.append('unsupported_speech')
    if labels.get('transition') == 'hard_cut' and re.search(
        r'\bgradual\w*\b|\bfad(?:e|es|ing)\b', text, re.IGNORECASE
    ):
        findings.append('unsupported_transition')
    findings = sorted(set(findings))
    # Correctness is supplied by a fixture annotation, never inferred from completion.
    correctness = (
        'not_evaluated'
        if completion != 'complete'
        else 'fail'
        if findings
        else 'pass'
        if labels
        else 'unlabelled'
    )
    return {
        'case_id': case['case_id'],
        'completion': completion,
        'correctness': correctness,
        'findings': findings,
        'case_sha256': input_identity(case),
        'label_scope': 'small explicit fixture facts; not general answer quality',
    }


def labelled_cases() -> list[dict]:
    return json.loads((Path(__file__).parent / 'quality_cases.json').read_text())


def check_cases() -> list[dict]:
    results = []
    for case in labelled_cases():
        result = evaluate(case)
        expected = case['expected']
        if any(result[key] != expected[key] for key in expected):
            raise AssertionError(f'Quality boundary changed for {case["case_id"]}: {result}')
        results.append(result)
    return results


def main() -> int:
    record = {
        'provider_calls': 0,
        'source_sha256': source_identity(),
        'package_versions': package_versions(),
        'cases': check_cases(),
        'scope': 'Offline labelled records. No new model quality measurements.',
    }
    print(json.dumps(record, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
