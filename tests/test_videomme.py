"""Video-MME: sampling, letter extraction, and an offline run of the catalog."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import replace

import pytest

from video_benchmark.config import load_config
from video_benchmark.videomme import runner
from video_benchmark.videomme.export import export_run, summarize
from video_benchmark.videomme.sample import sample_questions, unique_videos
from video_benchmark.videomme.schema import OSS_EVIDENCE_MAX_CHARS, reset_catalog
from video_benchmark.videomme.scoring import extract_letter_impl, is_correct_impl, window_text_impl


def _fake_rows() -> list[dict]:
    rows = []
    for duration in ('short', 'medium', 'long'):
        for v in range(4):
            video_id = f'{duration[0]}{v:02d}'
            for q in range(3):
                rows.append(
                    {
                        'video_id': video_id,
                        'duration': duration,
                        'domain': 'Knowledge',
                        'url': f'https://youtube.com/watch?v={video_id}',
                        'question_id': f'{video_id}-{q}',
                        'task_type': 'OCR',
                        'question': f'Q {video_id} {q}?',
                        'options': ['A. a', 'B. b', 'C. c', 'D. d'],
                        'answer': 'A',
                    }
                )
    return rows


def test_sample_is_stratified_and_deterministic():
    rows = _fake_rows()
    first = sample_questions(rows, n=9, seed=7)
    assert Counter(q['duration'] for q in first) == {'short': 3, 'medium': 3, 'long': 3}
    assert [q['question_id'] for q in first] == [
        q['question_id'] for q in sample_questions(rows, n=9, seed=7)
    ]
    # All three questions of a video are taken together, so shared evidence amortizes.
    assert len(unique_videos(first)) == 3


def test_extract_letter():
    assert extract_letter_impl('Because reasons.\nAnswer: C') == 'C'
    assert extract_letter_impl('Final answer: **d**') == 'D'
    assert extract_letter_impl(r'The choice is \boxed{B}') == 'B'
    assert extract_letter_impl('I conclude the answer is A.') == 'A'
    assert extract_letter_impl('I think the choice is\nB') == 'B'
    assert extract_letter_impl('Answer: None') is None
    assert extract_letter_impl('options A, B, C, D') is None
    assert is_correct_impl('b', 'B') and not is_correct_impl(None, 'B')


def test_window_text_keeps_head_middle_and_end():
    text = 'H' * 5_000 + 'M' * 50_000 + 'T' * 5_000
    out = window_text_impl(text, OSS_EVIDENCE_MAX_CHARS)
    assert len(out) <= OSS_EVIDENCE_MAX_CHARS
    assert out.startswith('H') and out.endswith('T') and 'M' in out
    assert window_text_impl('short', 100) == 'short'


def test_videomme_config_defaults(monkeypatch):
    for key in ('VIDEOME_VISION_SAMPLE_KEYFRAMES', 'VIDEOME_FRAME_SELECT_BUDGET', 'NOVA_MODEL_ID'):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv('VISION_SAMPLE_KEYFRAMES', '24')
    cfg = runner.videomme_config(load_config())
    assert (cfg.vision_sample_keyframes, cfg.frame_select_budget) == (32, 24)
    assert cfg.nova_model_id == 'amazon.nova-lite-v1:0'
    assert cfg.oss_asr == 'gemini'
    assert runner.parse_paths(None) == {'1', '2'}
    with pytest.raises(ValueError, match='Unknown paths'):
        runner.parse_paths('4')


def test_summary_statistics():
    predictions = [
        {
            'question_id': f'q{i}',
            'video_id': f'v{i // 3}',
            'duration_bucket': 'short',
            'p1_correct': i % 2 == 0,
            'p1_letter': 'A',
            'p1_cost': 0.10,
            'p1_list_cost': 0.12,
            'p1_shared_cost': 0.0,
            'p2_correct': True,
            'p2_letter': 'A',
            'p2_cost': 0.02,
            'p2_list_cost': 0.02,
            'p2_shared_cost': 0.01,
        }
        for i in range(6)
    ]
    summary = summarize(predictions, ['1', '2'])
    assert summary['paths']['1']['correct'] == 3
    assert summary['paths']['2']['accuracy'] == 1.0
    comparison = summary['comparisons'][0]
    assert (comparison['a_only_correct'], comparison['b_only_correct']) == (0, 3)
    assert comparison['cost_ratio_a_over_b'] == pytest.approx(5.0)
    assert comparison['list_cost_ratio_a_over_b'] == pytest.approx(6.0)


def test_failed_answers_use_the_same_denominator_for_intervals_and_accuracy():
    predictions = [
        {
            'question_id': f'q{i}', 'video_id': 'v1', 'duration_bucket': 'short',
            'p1_correct': None, 'p1_letter': None, 'p1_cost': 0.0, 'p1_list_cost': 0.0,
            'p1_shared_cost': 0.0, 'p2_correct': True, 'p2_letter': 'B',
            'p2_cost': 0.1, 'p2_list_cost': 0.1, 'p2_shared_cost': 0.0,
        } for i in range(3)
    ]
    summary = summarize(predictions, ['1', '2'])
    assert summary['paths']['1']['accuracy'] == 0.0
    assert summary['paths']['1']['accuracy_ci95'] == (0.0, 0.0)
    assert summary['comparisons'][0]['accuracy_diff_ci95'] == (-1.0, -1.0)
    assert summary['comparisons'][0]['paired_cluster_p'] == 1.0
    assert summary['paths']['1']['by_duration']['long']['accuracy_ci95'] is None
    json.dumps(summary, allow_nan=False)


def test_missing_cost_is_unknown_in_summary_instead_of_free():
    prediction = {
        'question_id': 'q1', 'video_id': 'v1', 'duration_bucket': 'short',
        'p1_correct': True, 'p1_letter': 'B', 'p1_cost': None, 'p1_list_cost': None,
        'p1_shared_cost': 0.0, 'p1_accounting_error': 'missing usage',
    }
    block = summarize([prediction], ['1'])['paths']['1']
    assert block['accuracy'] == 1.0
    assert block['unknown_cost_questions'] == block['accounting_errors'] == 1
    assert block['total_cost_usd'] is None and block['mean_cost_usd'] is None
    assert block['mean_cost_ci95'] is None


@pytest.fixture
def fresh_catalog():
    reset_catalog()
    yield
    reset_catalog()


def test_offline_run(fresh_catalog, fake_gemini, test_video, tmp_path):
    config = replace(
        runner.videomme_config(load_config()),
        vision_sample_keyframes=4,
        frame_select_budget=3,
        gemini_synth_max_images=2,
    )
    questions = [
        {
            'question_id': f'v1-{i}',
            'video_id': 'v1',
            'duration': 'short',
            'domain': 'Knowledge',
            'url': 'https://example.com/v1',
            'task_type': 'OCR',
            'question': f'Question {i}?',
            'options': ['A. a', 'B. b', 'C. c', 'D. d'],
            'answer': answer,
        }
        for i, answer in enumerate(('B', 'C'))
    ]
    downloads = {'v1': str(test_video)}
    predictions, videos = runner.run_videomme(config, {'1', '1L', '2'}, questions, downloads)

    kinds = Counter(call['kind'] for call in fake_gemini.calls)
    # Evidence is built once per video; each question adds its own answer calls.
    assert kinds == {'caption': 4, 'asr': 1, 'native': 4, 'synthesis': 2}
    assert [p['question_id'] for p in predictions] == ['v1-0', 'v1-1']
    for p in predictions:
        assert p['p1_letter'] == p['p1l_letter'] == p['p2_letter'] == 'B'
        assert p['p2_shared_cost'] > 0
    assert [p['p2_correct'] for p in predictions] == [True, False]
    # Shared evidence cost splits evenly across the video's two questions.
    assert predictions[0]['p2_shared_cost'] == pytest.approx(predictions[1]['p2_shared_cost'])

    # A rerun inserts nothing and calls nothing.
    calls_before = len(fake_gemini.calls)
    runner.run_videomme(config, {'1', '1L', '2'}, questions, downloads)
    assert len(fake_gemini.calls) == calls_before

    assert predictions[0]['duration_sec'] == pytest.approx(4.0, abs=0.2)
    assert predictions[0]['p2_list_cost'] == pytest.approx(predictions[0]['p2_cost'])
    assert videos[0]['caption_calls'] == 4 and videos[0]['asr_calls'] == 1
    assert videos[0]['caption_cost'] + videos[0]['asr_cost'] == pytest.approx(
        predictions[0]['p2_shared_cost'] * 2
    )

    out = export_run(
        predictions=predictions,
        videos=videos,
        paths=['1', '1L', '2'],
        config=config,
        seed=0,
        n=2,
        export_base=tmp_path,
    )
    summary = json.loads((out / 'summary.json').read_text())
    assert summary['paths']['2']['accuracy'] == 0.5
    assert len((out / 'predictions.jsonl').read_text().splitlines()) == 2


def test_failed_cells_are_retried_once_with_their_own_batch(fresh_catalog, fake_gemini, test_video):
    config = replace(
        runner.videomme_config(load_config()),
        vision_sample_keyframes=4,
        frame_select_budget=3,
        gemini_synth_max_images=2,
    )
    questions = [
        {
            'question_id': f'{vid}-0',
            'video_id': vid,
            'duration': 'short',
            'domain': 'Knowledge',
            'url': f'https://example.com/{vid}',
            'task_type': 'OCR',
            'question': 'Question?',
            'options': ['A. a', 'B. b', 'C. c', 'D. d'],
            'answer': 'B',
        }
        for vid in ('v1', 'v2')
    ]
    fake_gemini.fail_kinds = {'caption'}
    downloads = {'v1': str(test_video), 'v2': str(test_video)}
    runner.run_videomme(config, {'2'}, questions, downloads)
    # Each video is its own batch: four captions, four retries, and no retry of v1 with v2.
    assert Counter(call['kind'] for call in fake_gemini.calls)['caption'] == 2 * (4 + 4)


def test_a_transcript_without_text_is_reported(fresh_catalog, fake_gemini, test_video, tmp_path):
    config = replace(
        runner.videomme_config(load_config()),
        vision_sample_keyframes=4,
        frame_select_budget=3,
        gemini_synth_max_images=2,
    )
    questions = [
        {
            'question_id': 'v1-0',
            'video_id': 'v1',
            'duration': 'short',
            'domain': 'Knowledge',
            'url': 'https://example.com/v1',
            'task_type': 'OCR',
            'question': 'Question?',
            'options': ['A. a', 'B. b', 'C. c', 'D. d'],
            'answer': 'B',
        }
    ]
    fake_gemini.empty_kinds = {'asr'}
    predictions, videos = runner.run_videomme(config, {'2'}, questions, {'v1': str(test_video)})
    # Billed, no error raised, no text: counted as empty rather than failed.
    assert (videos[0]['asr_failed'], videos[0]['asr_empty'], videos[0]['caption_empty']) == (
        0,
        1,
        0,
    )
    assert videos[0]['asr_cost'] > 0
    out = export_run(
        predictions=predictions,
        videos=videos,
        paths=['2'],
        config=config,
        seed=0,
        n=1,
        export_base=tmp_path,
    )
    assert json.loads((out / 'summary.json').read_text())['evidence']['asr']['empty'] == 1
    assert '1 calls, 0 failed, 1 returned no text' in (out / 'REPORT.md').read_text()


@pytest.mark.parametrize('kind', ['native', 'caption', 'asr', 'native_cache'])
def test_missing_or_ambiguous_usage_survives_prediction_collection(
    fresh_catalog, fake_gemini, test_video, kind
):
    config = replace(
        runner.videomme_config(load_config()), vision_sample_keyframes=4,
        frame_select_budget=3, gemini_synth_max_images=2,
    )
    if kind == 'native_cache':
        fake_gemini.ambiguous_cache_kinds = {'native'}
    else:
        fake_gemini.missing_usage_kinds = {kind}
    questions = [{
        'question_id': 'v1-0', 'video_id': 'v1', 'duration': 'short', 'domain': 'Knowledge',
        'url': 'https://example.com/v1', 'task_type': 'OCR', 'question': 'Question?',
        'options': ['A. a', 'B. b', 'C. c', 'D. d'], 'answer': 'B',
    }]
    predictions, _ = runner.run_videomme(config, {'1', '2'}, questions, {'v1': str(test_video)})
    path = '1' if kind.startswith('native') else '2'
    row = predictions[0]
    assert row[f'p{path}_correct'] is True  # answer preserved despite accounting failure
    assert row[f'p{path}_cost'] is None and row[f'p{path}_accounting_error']
    if kind != 'native_cache':
        assert row[f'p{path}_list_cost'] is None
    block = summarize(predictions, ['1', '2'])['paths'][path]
    assert block['unknown_cost_questions'] == 1 and block['total_cost_usd'] is None
    assert block['accuracy'] == 1.0
