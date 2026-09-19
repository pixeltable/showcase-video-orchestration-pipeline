"""No-network TableModel path-gating and apply-surface tests."""

from __future__ import annotations

import inspect

from video_benchmark.config import load_config
from video_benchmark.schema import (
    apply_pursuit_schema,
    build_core_models,
    model_column_names,
    plan_paths,
)
from video_benchmark.videomme import pipeline as videomme_pipeline
from video_benchmark.videomme import schema as videomme_schema


def test_path_12_vs_3_builds_different_keyframe_columns():
    config = load_config()
    demo = build_core_models(config, plan_paths(config, {'1', '2'}))
    oss = build_core_models(config, plan_paths(config, {'3'}))

    demo_kf = model_column_names(demo, 'keyframes')
    oss_kf = model_column_names(oss, 'keyframes')
    assert 'gemini_frame_insight' in demo_kf
    assert 'oss_frame_insight' not in demo_kf
    assert 'oss_frame_insight' in oss_kf
    assert 'gemini_frame_insight' not in oss_kf

    demo_vs = model_column_names(demo, 'video_sources')
    oss_vs = model_column_names(oss, 'video_sources')
    assert 'native_insight' in demo_vs
    assert 'native_insight' not in oss_vs
    assert 'oss_insight' not in demo_vs
    assert 'oss_insight' not in oss_vs


def test_path_1_omits_modular_views():
    config = load_config()
    native = build_core_models(config, plan_paths(config, {'1'}))
    assert model_column_names(native, 'keyframes') == set()
    assert model_column_names(native, 'audio_chunks') == set()
    assert 'native_insight' in model_column_names(native, 'video_sources')


def test_pursuit_setup_uses_tablemodel_update_all():
    from video_benchmark import pipeline, schema

    source = inspect.getsource(pipeline.setup_pipeline) + inspect.getsource(apply_pursuit_schema)
    assert 'update_all' in source
    assert 'create_table' not in source
    assert 'add_computed_column' not in source
    assert 'create_view' not in source
    assert 'TableModel' in inspect.getsource(schema.build_core_models)


def test_videomme_setup_uses_tablemodel_update_all():
    source = (
        inspect.getsource(videomme_pipeline.setup_pipeline)
        + inspect.getsource(videomme_schema.build_core_models)
        + inspect.getsource(videomme_schema.build_parent_models)
    )
    assert 'update_all' in source
    assert 'create_table' not in source
    assert 'add_computed_column' not in source
    assert 'create_view' not in source


def test_videomme_queries_filter_on_video_id():
    source = inspect.getsource(videomme_pipeline._register_scoped_queries)
    assert 'video_id == video_id' in source
    assert 'keyframes.query' not in source
