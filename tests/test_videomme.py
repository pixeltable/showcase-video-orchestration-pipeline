"""Unit tests for Video-MME sampling, letter extract, cost amortization."""

from __future__ import annotations

import pytest

from video_benchmark.videomme.pipeline import rollup_exceeds_child_count
from video_benchmark.videomme.runner import DEFAULT_PATHS as VIDEOME_DEFAULTS
from video_benchmark.videomme.runner import OSS_SYNTH_MAX_CHARS, manifest_is_reusable
from video_benchmark.videomme.runner import parse_paths as parse_videomme_paths
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
    assert extract_letter('options A, B, C, D') is None


def test_manifest_reuse_requires_matching_seed_and_n():
    payload = {
        'seed': 42,
        'n': 30,
        'downloads': {'v': '/tmp/v.mp4'},
        'questions': [{'video_id': 'v'}] * 30,
    }
    assert manifest_is_reusable(payload, n=30, seed=42)
    assert not manifest_is_reusable(payload, n=30, seed=7)
    assert not manifest_is_reusable(payload, n=12, seed=42)
    assert not manifest_is_reusable({'seed': 42, 'n': 30, 'questions': []}, n=30, seed=42)


def test_oss_synth_context_is_capped_for_local_model():
    from video_benchmark.videomme.scoring import window_shared_context

    big = 'A' * 80_000
    out = window_shared_context(big, video_duration_sec=30.0, max_chars=OSS_SYNTH_MAX_CHARS)
    assert len(out) <= OSS_SYNTH_MAX_CHARS
    assert OSS_SYNTH_MAX_CHARS <= 16_000


def test_videomme_frame_defaults_ignore_pursuit_env(monkeypatch):
    from dataclasses import replace

    from video_benchmark.config import load_config
    from video_benchmark.videomme.runner import apply_videomme_frame_defaults

    monkeypatch.setattr('video_benchmark.config.load_dotenv', lambda env_path=None: None)
    monkeypatch.setenv('VISION_SAMPLE_KEYFRAMES', '24')
    monkeypatch.setenv('FRAME_SELECT_BUDGET', '16')
    monkeypatch.delenv('VIDEOME_VISION_SAMPLE_KEYFRAMES', raising=False)
    monkeypatch.delenv('VIDEOME_FRAME_SELECT_BUDGET', raising=False)
    monkeypatch.delenv('VIDEOME_FRAME_CONTEXT_MAX_ENTRIES', raising=False)
    bumped = apply_videomme_frame_defaults(load_config())
    assert bumped.vision_sample_keyframes == 32
    assert bumped.frame_select_budget == 24

    monkeypatch.setenv('VIDEOME_VISION_SAMPLE_KEYFRAMES', '20')
    overridden = apply_videomme_frame_defaults(replace(bumped, vision_sample_keyframes=24))
    assert overridden.vision_sample_keyframes == 20


def test_videomme_default_paths_are_gemini_compare():
    assert parse_videomme_paths(None) == {'1', '2'}
    assert VIDEOME_DEFAULTS == {'1', '2'}


def test_videomme_parse_paths_rejects_fal():
    with pytest.raises(ValueError, match='Unknown paths'):
        parse_videomme_paths('4')


def test_rollup_exceeds_child_count_identity():
    assert not rollup_exceeds_child_count([{'x': 1}] * 24, 24)
    assert rollup_exceeds_child_count([{'x': 1}] * 48, 24)
    assert rollup_exceeds_child_count([{'x': 1}], 0)


def test_assemble_mcq_evidence_has_no_pursuit_rubric():
    from video_benchmark.udfs import _assemble_mcq_evidence_impl

    text = _assemble_mcq_evidence_impl(
        [{'text': 'hello', 'segment_start': 20.0, 'speaker': 'A'}],
        [{'pos_msec': 1000.0, 'segment_start': 0.0, 'frame_insight': 'a room'}],
        'Gemini',
    )
    assert 'Main Activities' not in text
    assert 'cohesive chronological summary' not in text
    assert '<audio_transcript>' in text
    assert 'a room' in text


def test_run_questions_path3_does_not_use_gemini_context():
    from video_benchmark.config import load_config
    from video_benchmark.videomme.runner import run_questions

    preds = run_questions(
        load_config(),
        [
            {
                'question_id': 'q1',
                'video_id': 'v1',
                'duration': 'short',
                'domain': 'x',
                'task_type': 'OCR',
                'question': 'What?',
                'options': ['A. a', 'B. b', 'C. c', 'D. d'],
                'answer': 'A',
            }
        ],
        {'v1': '/tmp/missing.mp4'},
        {
            'v1': {
                'shared_context': 'GEMINI EVIDENCE SHOULD NOT LEAK',
                'oss_shared_context': '',
                'video_duration_sec': 10.0,
                'shared_cost': 0.0,
                'oss_shared_cost': 0.0,
            }
        },
        paths={'3'},
    )
    assert preds[0]['oss_raw'].startswith('ERROR: missing oss_shared_context')
    assert 'GEMINI EVIDENCE SHOULD NOT LEAK' not in (preds[0]['oss_raw'] or '')
    assert preds[0]['oss_letter'] is None


def test_window_shared_context_long():
    from video_benchmark.videomme.scoring import window_shared_context

    big = 'HEAD' + ('x' * 80_000) + 'MID' + ('y' * 80_000) + 'TAIL'
    out = window_shared_context(big, video_duration_sec=2000.0, max_chars=10_000)
    assert 'HEAD' in out
    assert 'TAIL' in out
    assert 'mid window' in out
    assert 'MID' in out
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
