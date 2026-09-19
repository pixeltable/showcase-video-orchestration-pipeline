#!/usr/bin/env python3
"""Score exported tune A/B runs for native-parity heuristics (all enabled paths)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Allow running without installing the package when PYTHONPATH includes src/.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from video_benchmark.scoring import score_insight_text  # noqa: E402

# insight key → (path label, summary cost key)
_PATH_SPECS: tuple[tuple[str, str, str], ...] = (
    ('native_insight', 'native', 'native_cost'),
    ('gemini_orchestrated_insight', 'gemini', 'gemini_orchestrated_total'),
    ('oss_insight', 'oss', 'oss_cost'),
    ('fal_insight', 'fal', 'fal_cost'),
    ('nova_insight', 'nova', 'nova_cost'),
)


def main() -> int:
    export_dir = Path(sys.argv[1] if len(sys.argv) > 1 else 'results/tune-ab')
    rows: list[dict] = []

    insight_paths = sorted(export_dir.glob('*/insights.json'))
    # Allow scoring a single export directory that contains insights.json directly.
    if not insight_paths and (export_dir / 'insights.json').exists():
        insight_paths = [export_dir / 'insights.json']

    for insights_path in insight_paths:
        summary_path = insights_path.parent / 'summary.json'
        manifest_path = insights_path.parent / 'manifest.json'
        insights = json.loads(insights_path.read_text())
        summary = json.loads(summary_path.read_text()) if summary_path.exists() else {}
        manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
        tag = manifest.get('config', {}).get('benchmark_tune_tag') or insights_path.parent.name

        for path_key, label, cost_key in _PATH_SPECS:
            if path_key not in insights:
                continue
            text = str(insights.get(path_key, '') or '')
            scores = score_insight_text(text)
            rows.append(
                {
                    'tag': tag,
                    'path': label,
                    'words': len(text.split()),
                    'cost': summary.get(cost_key),
                    **scores,
                }
            )

    out = export_dir / 'TUNE_COMPARISON.md'
    lines = [
        '# Tune A/B Comparison',
        '',
        (
            '| tag | path | words | nice_pants | jay | chris | salary | '
            'tonight | complete | truncated | sections | no_spam | cost |'
        ),
        (
            '|-----|------|-------|------------|-----|-------|--------|'
            '---------|----------|-----------|----------|---------|------|'
        ),
    ]
    for row in rows:
        lines.append(
            f"| {row['tag']} | {row['path']} | {row['words']} | "
            f"{row['nice_pants']} | {row['jay_named']} | {row['chris_named']} | "
            f"{row['has_salary']} | {row['has_tonight']} | "
            f"{row['complete']} | {row['truncated']} | {row['has_sections']} | "
            f"{row['no_per_frame_spam']} | {row.get('cost')} |"
        )
    out.write_text('\n'.join(lines) + '\n')
    print(out)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
