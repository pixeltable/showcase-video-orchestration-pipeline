"""Saved model output stays inert, and its provenance remains visible in the preview."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_saved_output_cannot_execute_html_and_keeps_original_sdk(tmp_path: Path):
    spec = importlib.util.spec_from_file_location(
        'render_showcase', ROOT / 'scripts' / 'render_showcase.py'
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    (tmp_path / 'summary.json').write_text(
        json.dumps(
            {
                'query': '<img src=x onerror=alert(1)>',
                'duration_sec': 10,
                'run_id': 'saved-run',
                'paths': {
                    '2': {
                        'label': 'Orchestrated <script>alert(1)</script>',
                        'answer': '<script>alert(1)</script>',
                        'words': 1,
                        'cost_usd': None,
                        'scores': {},
                        'errors': {'caption': '<script>alert(1)</script>'},
                        'stages': {
                            'captions': {
                                'calls': 2,
                                'failed_calls': 0,
                                'unknown_cost_calls': 1,
                                'cost_usd': None,
                                'response_accounted_cost_usd': 0.001,
                            }
                        },
                    }
                },
            }
        )
    )
    (tmp_path / 'manifest.json').write_text(
        json.dumps({'pixeltable_version': '0.7.11', 'exported_utc': '2026-09-28'})
    )
    rendered = module.render(tmp_path)
    assert '<script>' not in rendered
    assert '<img src=x' not in rendered
    assert '&lt;script&gt;' in rendered
    assert '0.7.11' in rendered
    assert 'n/a response-accounted' in rendered
    assert 'n/a ($0.0010 known subtotal)' in rendered
    assert 'not a quality benchmark' in rendered
    assert 'unrecorded retry or failed-request charges' in rendered
