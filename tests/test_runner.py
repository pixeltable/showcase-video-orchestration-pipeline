"""Runner recompute contract tests."""

from __future__ import annotations

import inspect

from video_benchmark import runner


def test_runner_recomputes_intermediate_frame_columns():
    source = inspect.getsource(runner.run_benchmark)
    assert 'gemini_frame_context_summarized' in source
    assert 'oss_frame_context_deduped' in source
    assert 'oss_frame_context_summarized' in source
    assert 'oss_frame_context_compact' in source
    assert source.index('gemini_frame_context_summarized') < source.index(
        'gemini_orchestrated_context'
    )
    assert 'gemini_synthesis_contents' in source
    assert source.index("oss_frame_context_compact") < source.index(
        "_recompute_column(vs, 'oss_context'"
    )
    assert source.index("_recompute_column(vs, 'oss_context'") < source.index(
        "_recompute_column(vs, 'oss_insight'"
    )
    assert 'fal_insight' in source
    assert 'nova_insight' in source
    assert 'paths' in source


def test_runner_recomputes_cost_rollup_columns():
    source = inspect.getsource(runner.run_benchmark)
    assert 'gemini_vision_track_cost' in source
    assert 'gemini_asr_cost' in source
    assert 'gemini_synthesis_cost' in source
    assert 'gemini_orchestrated_insight' in source
    assert 'gemini_orchestrated_total' in source


def test_runner_warns_on_empty_intermediates():
    source = inspect.getsource(runner.run_benchmark)
    assert '_warn_list_context' in source
    assert 'gemini_frame_context_summarized' in source
    assert 'oss_frame_context_deduped' in source
    assert 'oss_frame_context_compact' in source


def test_runner_recompute_uses_path_gated_columns():
    source = inspect.getsource(runner.run_benchmark)
    recompute_src = inspect.getsource(runner._recompute_column)
    assert '_recompute_column' in source
    assert 'recompute_columns(column, cascade=cascade)' in recompute_src
    assert 'Soft-skip Path 3' in source
