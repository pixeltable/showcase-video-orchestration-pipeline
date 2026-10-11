#!/usr/bin/env python3
"""Render the repeated result tables from docs/paper/numbers.json; no provider calls.

Use --check to detect drift without changing published documents.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ORDER = ('1', '1L', '2', '4', '5')
LABELS = {
    '1': '1 Native',
    '1L': '1L Native, low resolution',
    '2': '2 Orchestrated',
    '4': '4 fal video-understanding',
    '5': '5 Amazon Nova',
}


def decimal(value: float | None, places: int = 3, prefix: str = '') -> str:
    return 'n/a' if value is None else f'{prefix}{value:.{places}f}'


def interval(
    value: float | None, bounds: list[float | None] | None, *, percent: bool = False
) -> str:
    if value is None or not bounds or len(bounds) != 2 or any(v is None for v in bounds):
        return 'n/a'
    factor, places = (100, 1) if percent else (1, 3)
    suffix = '%' if percent else ''
    return (
        f'{value * factor:.{places}f}{suffix} '
        f'[{bounds[0] * factor:.{places}f}, {bounds[1] * factor:.{places}f}]'
    )


def label(path: str, nova_model: str | None = None) -> str:
    if path == '5' and nova_model:
        tier = nova_model.rsplit('.', 1)[-1].split('-')[1].capitalize()
        return f'5 Amazon Nova {tier}'
    return LABELS[path]


def table(
    headers: list[str], rows: list[list[str]], widths: tuple[int, ...] | None = None
) -> str:
    lines = ['| ' + ' | '.join(headers) + ' |']
    widths = widths or (3,) * len(headers)
    # Pandoc uses separator lengths as relative PDF column widths.
    lines.append('| ' + ' | '.join(
        '-' * width + (':' if i else '') for i, width in enumerate(widths)
    ) + ' |')
    lines.extend('| ' + ' | '.join(row) + ' |' for row in rows)
    return '\n'.join(lines)


def render_tables(numbers: dict) -> dict[str, str]:
    pursuit = numbers['pursuit']
    vm = numbers['videomme']
    paths = vm['paths']
    clip_rows = []
    for path in ORDER:
        if path not in pursuit:
            continue
        rec = pursuit[path]
        hits = rec['clip_hits_mean']
        checks = numbers['clip_check_count']
        clip_rows.append([
            label(path, rec.get('nova_model')),
            decimal(rec['cost_mean'], 4, '$'),
            f'{hits:g}/{checks} (mean)' if hits != rec['clip_hits_min'] else f'{hits:g}/{checks}',
        ])

    comparison_rows, study_rows, accuracy_rows, cost_rows = [], [], [], []
    for path in ORDER:
        if path not in paths:
            continue
        rec = paths[path]
        name = label(path, vm.get('nova_model'))
        paper_name = name.replace('Amazon Nova', 'Nova')
        accuracy = interval(rec['accuracy'], rec['accuracy_ci95'], percent=True)
        comparison_rows.append([
            name, accuracy, decimal(rec['mean_list_cost_usd'], prefix='$'),
            decimal(rec['mean_cost_usd'], prefix='$'),
        ])
        if path in ('1', '1L', '2'):
            study_name = f'{name} (Pixeltable)' if path == '2' else name
            study_rows.append([study_name, *comparison_rows[-1][1:]])
        strata = [rec['by_duration'].get(bucket, {}).get('accuracy')
                  for bucket in ('short', 'medium', 'long')]
        accuracy_rows.append([
            paper_name, accuracy, *(decimal(v * 100, 1) + '%' if v is not None else 'n/a'
                              for v in strata), str(rec['failed_calls']),
        ])
        cache = rec.get('answer_input_cache_fraction')
        cache_label = 'none' if path == '5' else (
            f'{cache:.0%}' if cache is not None else 'n/a'
        )
        correct = rec['correct']
        total = rec['total_list_cost_usd']
        per_correct = total / correct if total is not None and correct else None
        cost_rows.append([
            paper_name, interval(rec['mean_list_cost_usd'], rec['mean_list_cost_ci95']),
            decimal(rec['mean_cost_usd']), cache_label, decimal(per_correct),
        ])
    return {
        'readme-study': table([
            'Approach', 'Accuracy [95% CI]', 'List / question', 'Accounted / question',
        ], study_rows),
        'results-clip': table(['Path', 'List price per answer', 'Clip phrase checks'], clip_rows),
        'results-videomme': table([
            'Path', 'Accuracy [95% CI]', 'List price per question',
            'Response-accounted per question',
        ], comparison_rows),
        'paper-accuracy': table([
            'Path', 'Accuracy [95% CI]', 'Short', 'Medium', 'Long', 'Failed calls',
        ], accuracy_rows, (30, 20, 7, 7, 6, 13)) + (
            f'\n\n: Video-MME accuracy on {vm["n_questions"]} questions '
            f'({paths["1"]["by_duration"]["short"]["n"]} short, '
            f'{paths["1"]["by_duration"]["medium"]["n"]} medium, '
            f'{paths["1"]["by_duration"]["long"]["n"]} long). '
            'A failed call counts as wrong.'
        ),
        'paper-cost': table([
            'Path', 'List per question [95% CI]', 'Accounted per question',
            'Input from cache', 'List per correct',
        ], cost_rows, (30, 25, 15, 14, 14)) + (
            '\n\n: Video-MME cost in USD. Orchestration\'s cost per question '
            'includes its allocated share of the video\'s captions and transcript.'
        ),
    }


def replace_block(document: str, name: str, content: str) -> str:
    start, end = f'<!-- results:{name}:start -->', f'<!-- results:{name}:end -->'
    if document.count(start) != 1 or document.count(end) != 1:
        raise ValueError(f'Expected one pair of result markers for {name}')
    pattern = re.escape(start) + r'.*?' + re.escape(end)
    updated, count = re.subn(
        pattern, lambda _: f'{start}\n\n{content}\n\n{end}', document, flags=re.S
    )
    if count != 1:
        raise ValueError(f'Result markers are out of order for {name}')
    return updated


def update_document(path: Path, tables: dict[str, str], *, check: bool) -> bool:
    original = path.read_text()
    updated = original
    for name, content in tables.items():
        updated = replace_block(updated, name, content)
    if updated == original:
        return False
    if not check:
        path.write_text(updated)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    tables = render_tables(json.loads((ROOT / 'docs/paper/numbers.json').read_text()))
    changed = []
    for path, prefix in (
        (ROOT / 'README.md', 'readme-'),
        (ROOT / 'docs/RESULTS.md', 'results-'),
        (ROOT / 'docs/paper/paper.md', 'paper-'),
    ):
        selected = {name: body for name, body in tables.items() if name.startswith(prefix)}
        if update_document(path, selected, check=args.check):
            changed.append(str(path.relative_to(ROOT)))
    if args.check and changed:
        print('Stale result tables: ' + ', '.join(changed))
        print('Run python scripts/render_paper_tables.py to update them from numbers.json.')
        return 1
    print('Result tables match numbers.json.' if args.check else 'Rendered result tables.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
