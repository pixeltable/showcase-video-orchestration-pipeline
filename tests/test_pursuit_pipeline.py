"""Offline end-to-end runs of the Pursuit catalog: a tiny video and a fake Gemini client."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import replace

import PIL.Image
import pytest

from video_benchmark import reporting, runner, schema
from video_benchmark.config import load_config


def _config():
    return replace(
        load_config(), vision_sample_keyframes=4, frame_select_budget=3, gemini_synth_max_images=2
    )


def _cost(tokens_by_rate: list[tuple[int, float]]) -> float:
    return sum(n * rate for n, rate in tokens_by_rate) / 1_000_000


# FakeGemini usage: every call reports 10 text tokens plus media tokens, 100 output tokens,
# and 50 thinking tokens on answer-writing calls. gemini-2.5-flash rates: $0.30 text/image/video,
# $1.00 audio, $2.50 output.
NATIVE_COST = _cost([(990, 0.30), (10, 0.30), (150, 2.50)])
CAPTION_COST = _cost([(290, 0.30), (10, 0.30), (100, 2.50)])
ASR_COST = _cost([(490, 1.00), (10, 0.30), (100, 2.50)])
SYNTHESIS_COST = _cost([(2000, 0.30), (150, 2.50)])


@pytest.fixture
def fresh_catalog():
    schema.reset_catalog()
    yield
    schema.reset_catalog()


def test_native_and_orchestrated_run_once_each(fresh_catalog, fake_gemini, test_video, tmp_path):
    config = _config()
    plan = schema.apply_schema(config, {'1', '1L', '2'})
    run_id, failed = runner.run_benchmark(plan, str(test_video), 'Who speaks?')

    assert failed == []
    kinds = Counter(call['kind'] for call in fake_gemini.calls)
    # One synthesis, after the evidence exists: no call on empty evidence, no recompute.
    assert kinds == {'native': 2, 'caption': 4, 'asr': 1, 'synthesis': 1}

    native_configs = [c['config'] for c in fake_gemini.calls if c['kind'] == 'native']
    assert sum(1 for cfg in native_configs if cfg is not None and cfg.media_resolution) == 1
    for call in fake_gemini.calls:
        if call['kind'] in {'caption', 'asr'}:
            assert call['config'].thinking_config.thinking_budget == 0
        if call['kind'] == 'synthesis':
            assert call['config'] is None

    synthesis = next(c for c in fake_gemini.calls if c['kind'] == 'synthesis')
    assert 'Speaker 2: Nice pants.' in synthesis['text']
    assert sum(isinstance(item, PIL.Image.Image) for item in synthesis['contents']) == 2
    assert isinstance(synthesis['contents'][-1], str)

    run = reporting.collect_run(run_id, plan, config)
    assert run['paths']['1']['answer'] == 'Native answer: two speakers talk.'
    assert run['paths']['1']['cost_usd'] == pytest.approx(NATIVE_COST)
    assert run['paths']['1']['usage']['thinking_tokens'] == 50
    orchestrated = run['paths']['2']
    assert orchestrated['answer'] == 'Orchestrated answer: two speakers talk.'
    stages = orchestrated['stages']
    assert stages['captions']['calls'] == 4
    assert stages['captions']['cost_usd'] == pytest.approx(4 * CAPTION_COST)
    assert stages['asr']['cost_usd'] == pytest.approx(ASR_COST)
    assert stages['synthesis']['cost_usd'] == pytest.approx(SYNTHESIS_COST)
    assert stages['synthesis']['frames_in_evidence'] == 3
    assert stages['synthesis']['images_attached'] == 2
    assert orchestrated['cost_usd'] == pytest.approx(4 * CAPTION_COST + ASR_COST + SYNTHESIS_COST)
    # No cache hits in the fake, so list price equals billed cost.
    assert orchestrated['list_cost_usd'] == pytest.approx(orchestrated['cost_usd'])
    assert run['paths']['1']['list_cost_usd'] == pytest.approx(NATIVE_COST)

    out = reporting.export_run(run_id, plan, config, str(test_video), tmp_path)
    summary = json.loads((out / 'summary.json').read_text())
    assert list(summary['paths']) == ['1', '1L', '2']
    manifest = json.loads((out / 'manifest.json').read_text())
    assert manifest['prices']['gemini_usd_per_1m']['gemini-2.5-flash']['output'] == 2.50
    frames = (out / 'keyframes.csv').read_text().splitlines()
    assert len(frames) == 1 + 4
    assert 'Nice pants' not in (out / 'keyframes.csv').read_text()


def test_runs_do_not_share_evidence(fresh_catalog, fake_gemini, test_video):
    plan = schema.apply_schema(_config(), {'2'})
    first, _ = runner.run_benchmark(plan, str(test_video), 'Who speaks?')
    second, _ = runner.run_benchmark(plan, str(test_video), 'Who speaks?')
    for run_id in (first, second):
        stages = reporting.collect_run(run_id, plan, _config())['paths']['2']['stages']
        assert stages['captions']['calls'] == 4
        assert stages['synthesis']['frames_in_evidence'] == 3


def test_failed_captions_are_reported_and_excluded(fresh_catalog, fake_gemini, test_video):
    fake_gemini.fail_kinds = {'caption'}
    plan = schema.apply_schema(_config(), {'2'})
    run_id, failed = runner.run_benchmark(plan, str(test_video), 'Who speaks?')

    assert failed == ['keyframes.gemini_caption_response']
    orchestrated = reporting.collect_run(run_id, plan, _config())['paths']['2']
    assert orchestrated['stages']['captions']['failed_calls'] == 4
    assert orchestrated['stages']['synthesis']['frames_in_evidence'] == 0
    # The synthesis still ran, on the transcript alone.
    assert orchestrated['answer'] == 'Orchestrated answer: two speakers talk.'


def test_a_transcript_without_text_is_reported_as_empty(fresh_catalog, fake_gemini, test_video):
    fake_gemini.empty_kinds = {'asr'}
    plan = schema.apply_schema(_config(), {'2'})
    run_id, failed = runner.run_benchmark(plan, str(test_video), 'Who speaks?')

    assert failed == []  # a recitation stop raises nothing
    stages = reporting.collect_run(run_id, plan, _config())['paths']['2']['stages']
    assert (stages['asr']['failed_calls'], stages['asr']['empty_outputs']) == (0, 1)
    assert stages['captions']['empty_outputs'] == 0


def test_changed_paths_require_reset(fresh_catalog):
    schema.apply_schema(_config(), {'1', '2'})
    with pytest.raises(schema.CatalogSchemaMismatch, match='--reset'):
        schema.apply_schema(_config(), {'1'})
    schema.reset_catalog()
    schema.apply_schema(_config(), {'1'})


def test_changed_udf_definition_requires_reset(fresh_catalog, monkeypatch):
    schema.apply_schema(_config(), {'1'})
    monkeypatch.setattr(
        schema.provenance, 'pipeline_identity', lambda *args: 'new-prompt-definition'
    )
    with pytest.raises(schema.CatalogSchemaMismatch, match='--reset'):
        schema.apply_schema(_config(), {'1'})


def test_missing_usage_preserves_answer_and_exports_unknown_cost(
    fresh_catalog, fake_gemini, test_video
):
    fake_gemini.missing_usage_kinds = {'native'}
    plan = schema.apply_schema(_config(), {'1'})
    run_id, failed = runner.run_benchmark(plan, str(test_video), 'Who speaks?')
    entry = reporting.collect_run(run_id, plan, _config())['paths']['1']
    assert failed
    assert entry['answer'] == 'Native answer: two speakers talk.'
    assert entry['cost_usd'] is None and entry['list_cost_usd'] is None
    assert entry['cost_status'] == 'unknown'
    assert 'cost is unknown' in entry['errors']['native_usage']


def test_upstream_blocked_response_is_visible_as_error_and_unknown_cost(
    fresh_catalog, fake_gemini, test_video
):
    fake_gemini.blocked_kinds = {'native'}
    plan = schema.apply_schema(_config(), {'1'})
    run_id, failed = runner.run_benchmark(plan, str(test_video), 'Who speaks?')
    entry = reporting.collect_run(run_id, plan, _config())['paths']['1']
    assert 'runs.native_response' in failed
    assert entry['answer'] == '' and entry['cost_usd'] is None
    assert 'not iterable' in entry['errors']['native_response']
    assert len(fake_gemini.calls) == 1


def test_missing_caption_usage_does_not_export_a_partial_total_as_complete(
    fresh_catalog, fake_gemini, test_video
):
    fake_gemini.missing_usage_kinds = {'caption'}
    plan = schema.apply_schema(_config(), {'2'})
    run_id, failed = runner.run_benchmark(plan, str(test_video), 'Who speaks?')
    entry = reporting.collect_run(run_id, plan, _config())['paths']['2']
    assert failed
    assert entry['answer'] == 'Orchestrated answer: two speakers talk.'
    assert entry['cost_usd'] is None and entry['list_cost_usd'] is None
    assert entry['stages']['captions']['unknown_cost_calls'] == 4
    assert entry['stages']['captions']['failed_calls'] == 0
