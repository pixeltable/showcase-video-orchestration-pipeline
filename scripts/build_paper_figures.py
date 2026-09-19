#!/usr/bin/env python3
"""Generate paper figures from five-path benchmark exports."""

from __future__ import annotations

import csv
import io
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESULTS = PROJECT_ROOT / 'results'
OUT_DIR = PROJECT_ROOT / 'docs' / 'paper' / 'figures'

PRIMARY_RUN = RESULTS / '20260710T040910Z'
LITE_RUN = RESULTS / '20260710T025835Z'

PATH_ORDER = ('native', 'gemini', 'oss', 'fal', 'nova')
PATH_LABELS = {
    'native': '1 Gemini\nnative',
    'gemini': '2 Gemini\norchestrated',
    'oss': '3 OSS',
    'fal': '4 fal\n(120s cap)',
    'nova': '5 Nova Pro',
}
SAMPLE_METRICS = ('nice_pants', 'jay', 'chris', 'salary', 'tonight')
GENERAL_METRICS = ('complete', 'sections', 'no_spam')


def _parse_bool(value: str) -> bool:
    return value.strip().lower() == 'true'


def load_tune_comparison(path: Path) -> list[dict]:
    text = path.read_text()
    lines = [ln for ln in text.splitlines() if ln.startswith('|') and '---' not in ln]
    if not lines:
        raise FileNotFoundError(f'No table rows in {path}')
    # Drop header separator already filtered; first line is header.
    reader = csv.DictReader(io.StringIO('\n'.join(lines)), delimiter='|')
    rows: list[dict] = []
    for raw in reader:
        # csv with | leaves empty first/last keys
        cleaned = {k.strip(): (v or '').strip() for k, v in raw.items() if k and k.strip()}
        if cleaned.get('path') in {'path', ''}:
            continue
        row = {
            'path': cleaned['path'],
            'words': int(cleaned['words']),
            'cost': float(cleaned['cost']),
            'nice_pants': _parse_bool(cleaned['nice_pants']),
            'jay': _parse_bool(cleaned['jay']),
            'chris': _parse_bool(cleaned['chris']),
            'salary': _parse_bool(cleaned['salary']),
            'tonight': _parse_bool(cleaned['tonight']),
            'complete': _parse_bool(cleaned['complete']),
            'truncated': _parse_bool(cleaned['truncated']),
            'sections': _parse_bool(cleaned['sections']),
            'no_spam': _parse_bool(cleaned['no_spam']),
        }
        rows.append(row)
    return rows


def _by_path(rows: list[dict]) -> dict[str, dict]:
    return {r['path']: r for r in rows}


def fig_cost_by_path(rows: list[dict], out: Path) -> None:
    by = _by_path(rows)
    labels = [PATH_LABELS[p] for p in PATH_ORDER]
    costs = [by[p]['cost'] for p in PATH_ORDER]
    colors = ['#4C78A8', '#F58518', '#54A24B', '#E45756', '#B279A2']

    fig, ax = plt.subplots(figsize=(8.5, 4.2))
    bars = ax.bar(labels, costs, color=colors, width=0.72)
    ax.set_ylabel('Estimated cost (USD)')
    ax.set_title('Five-path cost on Pursuit (~255s); fal billed on 120s cap')
    ax.set_ylim(0, max(costs) * 1.25)
    for bar, cost in zip(bars, costs):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.005,
            f'${cost:.3f}',
            ha='center',
            va='bottom',
            fontsize=9,
        )
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    fig.tight_layout()
    fig.savefig(out, dpi=200)
    plt.close(fig)


def fig_quality_heatmap(rows: list[dict], out: Path) -> None:
    by = _by_path(rows)
    metrics = SAMPLE_METRICS + GENERAL_METRICS
    matrix = np.array(
        [[1.0 if by[p][m] else 0.0 for m in metrics] for p in PATH_ORDER],
        dtype=float,
    )
    fig, ax = plt.subplots(figsize=(8.5, 4.0))
    im = ax.imshow(matrix, cmap='RdYlGn', vmin=0, vmax=1, aspect='auto')
    ax.set_xticks(range(len(metrics)))
    ax.set_xticklabels(metrics, rotation=35, ha='right')
    ax.set_yticks(range(len(PATH_ORDER)))
    ax.set_yticklabels([PATH_LABELS[p].replace('\n', ' ') for p in PATH_ORDER])
    ax.set_title('Heuristic quality matrix (True=green)')
    for i in range(matrix.shape[0]):
        for j in range(matrix.shape[1]):
            ax.text(
                j,
                i,
                '✓' if matrix[i, j] > 0.5 else '✗',
                ha='center',
                va='center',
                color='black',
                fontsize=11,
            )
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04, ticks=[0, 1], label='pass')
    fig.tight_layout()
    fig.savefig(out, dpi=200)
    plt.close(fig)


def fig_cost_vs_quality(rows: list[dict], out: Path) -> None:
    by = _by_path(rows)
    fig, ax = plt.subplots(figsize=(7.5, 5.0))
    colors = {
        'native': '#4C78A8',
        'gemini': '#F58518',
        'oss': '#54A24B',
        'fal': '#E45756',
        'nova': '#B279A2',
    }
    for p in PATH_ORDER:
        r = by[p]
        hits = sum(1 for m in SAMPLE_METRICS if r[m])
        ax.scatter(
            r['cost'],
            hits,
            s=180,
            color=colors[p],
            edgecolors='black',
            linewidths=0.6,
            zorder=3,
        )
        ax.annotate(
            PATH_LABELS[p].replace('\n', ' '),
            (r['cost'], hits),
            textcoords='offset points',
            xytext=(8, 6),
            fontsize=9,
        )
    ax.set_xlabel('Estimated cost (USD)')
    ax.set_ylabel('Sample heuristic hits (of 5)')
    ax.set_ylim(-0.3, 5.5)
    ax.set_xlim(-0.01, max(by[p]['cost'] for p in PATH_ORDER) * 1.15)
    ax.set_title('Cost vs sample-heuristic quality')
    ax.grid(True, alpha=0.3)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    fig.tight_layout()
    fig.savefig(out, dpi=200)
    plt.close(fig)


def fig_nova_ablation(pro_rows: list[dict], lite_rows: list[dict], out: Path) -> None:
    """Optional fourth figure used in paper ablation section."""
    pro = _by_path(pro_rows)['nova']
    lite = _by_path(lite_rows)['nova']
    labels = ['Nova Lite', 'Nova Pro']
    costs = [lite['cost'], pro['cost']]
    words = [lite['words'], pro['words']]

    fig, axes = plt.subplots(1, 2, figsize=(8.0, 3.6))
    axes[0].bar(labels, costs, color=['#C9A0DC', '#B279A2'])
    axes[0].set_ylabel('Cost (USD)')
    axes[0].set_title('Nova cost')
    for i, c in enumerate(costs):
        axes[0].text(i, c + 0.002, f'${c:.3f}', ha='center', fontsize=9)
    axes[1].bar(labels, words, color=['#C9A0DC', '#B279A2'])
    axes[1].set_ylabel('Words')
    axes[1].set_title('Nova answer length')
    for i, w in enumerate(words):
        axes[1].text(i, w + 3, str(w), ha='center', fontsize=9)
    for ax in axes:
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
    fig.suptitle('Nova Lite vs Nova Pro (same clip / prompt)')
    fig.tight_layout()
    fig.savefig(out, dpi=200)
    plt.close(fig)


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pro_rows = load_tune_comparison(PRIMARY_RUN / 'TUNE_COMPARISON.md')
    lite_rows = load_tune_comparison(LITE_RUN / 'TUNE_COMPARISON.md')

    fig_cost_by_path(pro_rows, OUT_DIR / 'cost_by_path.png')
    fig_quality_heatmap(pro_rows, OUT_DIR / 'quality_heatmap.png')
    fig_cost_vs_quality(pro_rows, OUT_DIR / 'cost_vs_quality.png')
    fig_nova_ablation(pro_rows, lite_rows, OUT_DIR / 'nova_lite_vs_pro.png')

    print(f'Wrote figures to {OUT_DIR}')
    for name in (
        'cost_by_path.png',
        'quality_heatmap.png',
        'cost_vs_quality.png',
        'nova_lite_vs_pro.png',
    ):
        path = OUT_DIR / name
        print(f'  {name} ({path.stat().st_size} bytes)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
