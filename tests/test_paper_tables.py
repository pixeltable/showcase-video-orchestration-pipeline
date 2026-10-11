"""Published table drift is detectable without overwriting the historical evidence."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    'paper_tables', ROOT / 'scripts/render_paper_tables.py'
)
assert spec and spec.loader
paper_tables = importlib.util.module_from_spec(spec)
spec.loader.exec_module(paper_tables)


def test_unknown_totals_and_no_correct_answers_remain_unknown():
    numbers = json.loads((ROOT / 'docs/paper/numbers.json').read_text())
    numbers['clip_check_count'] = 5
    rec = numbers['videomme']['paths']['2']
    rec.update(mean_cost_usd=None, mean_list_cost_usd=None, total_list_cost_usd=None, correct=0)
    rec['mean_list_cost_ci95'] = [None, None]
    tables = paper_tables.render_tables(numbers)
    row = next(line for line in tables['paper-cost'].splitlines() if '2 Orchestrated' in line)
    assert row.split('|')[2].strip() == 'n/a'
    assert row.split('|')[3].strip() == 'n/a'
    assert row.split('|')[5].strip() == 'n/a'
    assert '0.000' not in row
    assert 'n/a' in next(
        line for line in tables['results-videomme'].splitlines() if '2 Orchestrated' in line
    )


def test_check_detects_drift_without_touching_document(tmp_path):
    doc = tmp_path / 'paper.md'
    original = (
        'Intro\n<!-- results:cost:start -->\n\nstale\n\n'
        '<!-- results:cost:end -->\nConclusion\n'
    )
    doc.write_text(original)
    assert paper_tables.update_document(doc, {'cost': 'fresh'}, check=True)
    assert doc.read_text() == original
    assert paper_tables.update_document(doc, {'cost': 'fresh'}, check=False)
    assert doc.read_text() == original.replace('stale', 'fresh')
    assert not paper_tables.update_document(doc, {'cost': 'fresh'}, check=True)


def test_missing_or_duplicate_markers_cannot_silently_publish():
    with pytest.raises(ValueError, match='one pair'):
        paper_tables.replace_block('No markers', 'cost', 'table')
    with pytest.raises(ValueError, match='one pair'):
        paper_tables.replace_block(
            '<!-- results:cost:start -->' * 2 + '<!-- results:cost:end -->', 'cost', 'table'
        )
    with pytest.raises(ValueError, match='out of order'):
        paper_tables.replace_block(
            '<!-- results:cost:end -->\nstale\n<!-- results:cost:start -->', 'cost', 'table'
        )


def test_pdf_captions_stay_inside_generated_blocks():
    numbers = json.loads((ROOT / 'docs/paper/numbers.json').read_text())
    tables = paper_tables.render_tables(numbers)
    for name in ('paper-accuracy', 'paper-cost'):
        rendered = paper_tables.replace_block(
            f'<!-- results:{name}:start -->\nold\n<!-- results:{name}:end -->',
            name, tables[name],
        )
        assert '\n\n: Video-MME' in rendered
        assert rendered.index(': Video-MME') < rendered.index(f'<!-- results:{name}:end -->')
