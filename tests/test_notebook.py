"""Execute the inspection notebook on isolated native and modular catalogs without calls."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from video_benchmark import reporting, runner, schema
from video_benchmark.config import load_config


@pytest.mark.parametrize('paths', [{'1'}, {'1', '2'}])
def test_notebook_inspects_selected_paths_without_model_calls(
    paths, fake_gemini, test_video, tmp_path
):
    schema.reset_catalog()
    try:
        config = replace(load_config(), vision_sample_keyframes=4, frame_select_budget=3)
        plan = schema.apply_schema(config, paths)
        run_id, failed = runner.run_benchmark(plan, str(test_video), 'Who speaks?')
        assert not failed
        reporting.export_run(run_id, plan, config, str(test_video), tmp_path)
        calls_before = len(fake_gemini.calls)
        notebook_path = Path(__file__).resolve().parents[1] / 'notebooks/pipeline_analytics.ipynb'
        notebook = json.loads(notebook_path.read_text())
        namespace = {'display': lambda result: None}
        for cell in notebook['cells']:
            if cell['cell_type'] != 'code':
                continue
            source = ''.join(cell['source'])
            exec(compile(source, str(notebook_path), 'exec'), namespace)
            if 'export_root =' in source:
                namespace['export_root'] = tmp_path
        assert namespace['run_id'] == run_id
        assert len(fake_gemini.calls) == calls_before
    finally:
        schema.reset_catalog()
