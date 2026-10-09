#!/usr/bin/env python3
"""Build the paper's figures and numbers from exported runs (no catalog, no API calls).

    python scripts/build_paper_figures.py [--pursuit results/paper/pursuit]
                                          [--videomme results/paper/videomme/<run>]

Writes docs/paper/figures/*.png and docs/paper/numbers.json, the analysis artifact for
the result figures and repeated result tables.
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402

from video_benchmark.paths import PATH_LABELS  # noqa: E402
from video_benchmark.pricing import (  # noqa: E402
    gemini_cost_parts_impl,
    nova_cost_impl,
    uncached_usage_impl,
)
from video_benchmark.scoring import CLIP_CHECKS  # noqa: E402
from video_benchmark.videomme.export import summarize  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FIGURES = ROOT / 'docs' / 'paper' / 'figures'
NUMBERS = ROOT / 'docs' / 'paper' / 'numbers.json'
V1_VIDEOMME = ROOT / 'docs' / 'paper' / 'v1_videomme.json'

# Categorical palette in fixed order (validated: adjacent CVD dE >= 9.1, normal-vision >= 19.6).
SLOTS = ('#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300')
PATH_ORDER = ('1', '1L', '2', '3', '4', '5')
PATH_COLOR = dict(zip(PATH_ORDER, SLOTS))
PATH_MARKER = {'1': 'o', '1L': 's', '2': 'D', '3': '^', '4': 'v', '5': 'P'}
SHORT = {
    '1': 'Path 1 native',
    '1L': 'Path 1L native, low res',
    '2': 'Path 2 orchestrated',
    '3': 'Path 3 local',
    '4': 'Path 4 fal',
    '5': 'Path 5 Nova',
}


def _label(path: str, nova_model: str | None = None) -> str:
    """Legend name of a path; Path 5 names its Nova tier (amazon.nova-lite-v1:0 -> Nova Lite)."""
    if path == '5' and nova_model:
        tier = nova_model.rsplit('.', 1)[-1].split('-')[1]
        return f'Path 5 Nova {tier.capitalize()}'
    return SHORT[path]


PART_ORDER = ('input_VIDEO', 'input_AUDIO', 'input_IMAGE', 'input_TEXT', 'output', 'thinking')
PART_LABEL = {
    'input_VIDEO': 'video input',
    'input_AUDIO': 'audio input',
    'input_IMAGE': 'image input',
    'input_TEXT': 'text input',
    'output': 'output',
    'thinking': 'thinking',
}
PART_COLOR = dict(zip(PART_ORDER, SLOTS))
INK, MUTED, GRID, SURFACE = '#0b0b0b', '#52514e', '#e4e3df', '#fcfcfb'

plt.rcParams.update(
    {
        'font.size': 9,
        'axes.edgecolor': MUTED,
        'axes.labelcolor': INK,
        'axes.titlesize': 10,
        'axes.spines.top': False,
        'axes.spines.right': False,
        'xtick.color': MUTED,
        'ytick.color': MUTED,
        'figure.facecolor': SURFACE,
        'axes.facecolor': SURFACE,
        'savefig.facecolor': SURFACE,
        'legend.frameon': False,
    }
)


def _latest(parent: Path) -> Path:
    runs = sorted(p for p in parent.iterdir() if (p / 'summary.json').exists())
    if not runs:
        raise FileNotFoundError(f'No exported runs under {parent}')
    return runs[-1]


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _parts(entry: dict, model: str, nova_model: str) -> dict[str, float]:
    """A path's list-price cost (no implicit-cache discount) by billed part, over its calls."""
    usages = [entry['usage']] if entry.get('usage') else []
    usages += [stage['usage'] for stage in (entry.get('stages') or {}).values() if stage['usage']]
    parts: dict[str, float] = {}
    for usage in usages:
        if 'input_by_modality' in usage:
            split = gemini_cost_parts_impl(uncached_usage_impl(usage), model)
        else:  # Nova
            split = {
                'input_VIDEO': nova_cost_impl({**usage, 'output_tokens': 0}, nova_model),
                'output': nova_cost_impl({**usage, 'input_tokens': 0}, nova_model),
            }
        for key, usd in split.items():
            parts[key] = parts.get(key, 0.0) + usd
    return parts


def pursuit_numbers(pursuit_dirs: list[Path]) -> dict:
    runs = []
    summaries = sorted(p for d in pursuit_dirs for p in d.glob('*/summary.json'))
    for summary_path in summaries:
        manifest = json.loads((summary_path.parent / 'manifest.json').read_text())
        runs.append((json.loads(summary_path.read_text()), manifest['config']))
    per_path: dict[str, dict] = {}
    for summary, config in runs:
        for path, entry in summary['paths'].items():
            rec = per_path.setdefault(
                path,
                {'costs': [], 'billed': [], 'words': [], 'clip_hits': [], 'parts': [], 'runs': 0},
            )
            rec['runs'] += 1
            rec['nova_model'] = config['nova_model_id']
            parts = _parts(entry, config['gemini_model'], config['nova_model_id'])
            if entry['cost_usd'] is not None:
                rec['billed'].append(entry['cost_usd'])
                # fal and local paths report no usage: their list price is their cost.
                rec['costs'].append(sum(parts.values()) if parts else entry['cost_usd'])
            rec['words'].append(entry['words'])
            rec['clip_hits'].append(sum(entry['scores'][c] for c in CLIP_CHECKS))
            rec['parts'].append(parts)
            if entry.get('stages'):
                for stage, info in entry['stages'].items():
                    rec.setdefault(f'{stage}_costs', []).append(info['cost_usd'])
    out = {}
    for path, rec in per_path.items():
        costs = rec['costs']
        parts = {
            key: statistics.mean(p.get(key, 0.0) for p in rec['parts'])
            for key in {k for p in rec['parts'] for k in p}
        }
        out[path] = {
            'runs': rec['runs'],
            'billed_mean': statistics.mean(rec['billed']) if rec['billed'] else None,
            'billed_min': min(rec['billed']) if rec['billed'] else None,
            'cost_mean': statistics.mean(costs) if costs else None,
            'cost_min': min(costs) if costs else None,
            'cost_max': max(costs) if costs else None,
            'cost_sd': statistics.stdev(costs) if len(costs) > 1 else 0.0,
            'words_mean': statistics.mean(rec['words']),
            'clip_hits_mean': statistics.mean(rec['clip_hits']),
            'clip_hits_min': min(rec['clip_hits']),
            'parts_mean': parts,
            'nova_model': rec['nova_model'] if path == '5' else None,
            **{key: statistics.mean(v) for key, v in rec.items() if key.endswith('_costs') and v},
        }
    return out


def fig_pursuit_breakdown(numbers: dict, out: Path) -> None:
    # fal (Path 4) bills per second with no token usage, at a cost 6x the Gemini paths: text only.
    paths = [
        p for p in PATH_ORDER if p in numbers and p != '4' and numbers[p]['cost_mean'] is not None
    ]
    fig, ax = plt.subplots(figsize=(6.5, 0.45 * len(paths) + 1.3))
    for row, path in enumerate(reversed(paths)):
        parts = numbers[path]['parts_mean']
        left = 0.0
        for key in PART_ORDER:
            width = parts.get(key, 0.0)
            if width <= 0:
                continue
            ax.barh(
                row, width, left=left, color=PART_COLOR[key], edgecolor=SURFACE, lw=1, height=0.6
            )
            left += width
        rec = numbers[path]
        total = rec['cost_mean']
        if rec['runs'] > 1:
            ax.errorbar(
                total,
                row,
                xerr=[[total - rec['cost_min']], [rec['cost_max'] - total]],
                fmt='none',
                ecolor=INK,
                elinewidth=1,
                capsize=3,
            )
        label = f'${total:.4f}' + (f'  (mean of {rec["runs"]})' if rec['runs'] > 1 else '')
        ax.text(rec['cost_max'] + 0.0008, row, label, va='center', color=INK, fontsize=8)
    ax.set_yticks(range(len(paths)), [_label(p, numbers[p]['nova_model']) for p in reversed(paths)])
    ax.set_xlabel('USD per run at list price (Pursuit clip, 255 s; whiskers: min-max of runs)')
    ax.xaxis.grid(True, color=GRID, lw=0.6)
    ax.set_axisbelow(True)
    ax.set_xlim(0, max(numbers[p]['cost_max'] for p in paths) * 1.35)
    handles = [plt.Rectangle((0, 0), 1, 1, color=PART_COLOR[k]) for k in PART_ORDER]
    ax.legend(
        handles,
        [PART_LABEL[k] for k in PART_ORDER],
        ncols=6,
        loc='upper center',
        bbox_to_anchor=(0.45, -0.28 if len(paths) > 3 else -0.4),
        fontsize=8,
        handlelength=1,
        columnspacing=1,
    )
    ax.set_title('Where the money goes: cost by billed part', loc='left')
    fig.tight_layout()
    fig.savefig(out, dpi=200, bbox_inches='tight')
    plt.close(fig)


def videomme_numbers(run_dir: Path) -> dict:
    predictions = _read_jsonl(run_dir / 'predictions.jsonl')
    videos = _read_jsonl(run_dir / 'videos.jsonl')
    manifest = json.loads((run_dir / 'manifest.json').read_text())
    # Reanalyse the fixed predictions with current inference; never relabel the original
    # provider calls as a new experiment or overwrite the committed run exports.
    summary = summarize(predictions, manifest['paths'])
    for path, rec in summary['paths'].items():
        usages = [row.get(f'p{path.lower()}_usage') or {} for row in predictions]
        input_tokens = sum(usage.get('input_tokens', 0) for usage in usages)
        rec['answer_input_cache_fraction'] = (
            sum(usage.get('cached_tokens', 0) for usage in usages) / input_tokens
            if input_tokens and any('cached_tokens' in usage for usage in usages) else None
        )
    return {
        'summary': summary,
        'predictions': predictions,
        'videos': videos,
        'nova_model': manifest['config']['nova_model_id'],
    }


def answered_comparison(vm: dict) -> dict:
    """The run restricted to questions every Gemini path answered: a failed call counts as wrong
    in the main results, so this separates provider refusals from answer quality."""
    gemini = [p for p in ('1', '1L', '2') if p in vm['summary']['paths']]
    failed = {
        r['question_id']: [p for p in gemini if r.get(f'p{p.lower()}_error')]
        for r in vm['predictions']
    }
    kept = [r for r in vm['predictions'] if not failed[r['question_id']]]
    return {
        'excluded': {qid: paths for qid, paths in failed.items() if paths},
        'summary': summarize(kept, list(vm['summary']['paths'])),
    }


def v1_comparison(vm: dict) -> dict:
    """This run's results on the 30 questions of the earlier release's Video-MME slice."""
    v1 = json.loads(V1_VIDEOMME.read_text())
    ids = set(v1['question_ids'])
    rows = [r for r in vm['predictions'] if r['question_id'] in ids]
    ours = {'n': len(rows)}
    for path, name in (('1', 'native'), ('1l', 'native_low'), ('2', 'orchestrated')):
        if f'p{path}_correct' not in (rows[0] if rows else {}):
            continue
        ours[f'{name}_correct'] = sum(1 for r in rows if r[f'p{path}_correct'])
        ours[f'{name}_total_list_cost_usd'] = sum(r[f'p{path}_list_cost'] for r in rows)
        ours[f'{name}_total_cost_usd'] = sum(r[f'p{path}_cost'] for r in rows)
    return {'earlier': v1['reported'], 'this_paper': ours}


def fig_videomme_accuracy(vm: dict, out: Path) -> None:
    summary = vm['summary']
    paths = [p for p in PATH_ORDER if p in summary['paths']]
    groups = [
        ('short', 'Short\n(<2 min)'),
        ('medium', 'Medium\n(4-15 min)'),
        ('long', 'Long\n(30-60 min)'),
        ('all', 'All'),
    ]
    width = 0.8 / len(paths)
    fig, ax = plt.subplots(figsize=(6.5, 3.0))
    for i, path in enumerate(paths):
        block = summary['paths'][path]
        xs, ys, lo, hi = [], [], [], []
        for g, (bucket, _) in enumerate(groups):
            b = block if bucket == 'all' else block['by_duration'][bucket]
            if not b['n']:
                continue
            xs.append(g - 0.4 + width * (i + 0.5))
            ys.append(b['accuracy'])
            lo.append(b['accuracy'] - b['accuracy_ci95'][0])
            hi.append(b['accuracy_ci95'][1] - b['accuracy'])
        ax.bar(
            xs,
            ys,
            width=width * 0.92,
            color=PATH_COLOR[path],
            edgecolor=SURFACE,
            lw=1,
            label=f'{_label(path, vm["nova_model"])} (n={block["n"]})',
        )
        ax.errorbar(xs, ys, yerr=[lo, hi], fmt='none', ecolor=INK, elinewidth=0.8, capsize=2)
    ax.axhline(0.25, color=MUTED, lw=0.8, ls=':')
    ax.text(-0.45, 0.265, 'chance', color=MUTED, fontsize=7, ha='left')
    ax.set_xticks(range(len(groups)), [label for _, label in groups])
    ax.set_ylabel('Accuracy (95% video-cluster bootstrap interval)')
    ax.set_ylim(0, 1.05)
    ax.yaxis.grid(True, color=GRID, lw=0.6)
    ax.set_axisbelow(True)
    ax.legend(ncols=3, fontsize=7.5, loc='upper center', bbox_to_anchor=(0.5, -0.22))
    ax.set_title('Video-MME accuracy by video length', loc='left')
    fig.tight_layout()
    fig.savefig(out, dpi=200, bbox_inches='tight')
    plt.close(fig)


def fig_videomme_cost_accuracy(vm: dict, out: Path) -> None:
    summary = vm['summary']
    fig, ax = plt.subplots(figsize=(6.5, 3.4))
    for path in PATH_ORDER:
        block = summary['paths'].get(path)
        if not block or not block['mean_list_cost_usd']:
            continue
        x, y = block['mean_list_cost_usd'], block['accuracy']
        (clo, chi), (alo, ahi) = block['mean_list_cost_ci95'], block['accuracy_ci95']
        ax.errorbar(
            x,
            y,
            xerr=[[x - clo], [chi - x]],
            yerr=[[y - alo], [ahi - y]],
            fmt='none',
            ecolor=PATH_COLOR[path],
            elinewidth=1,
            capsize=2,
            alpha=0.8,
        )
        ax.scatter(
            x,
            y,
            s=64,
            marker=PATH_MARKER[path],
            color=PATH_COLOR[path],
            edgecolors=SURFACE,
            linewidths=1.5,
            zorder=3,
        )
        # Label beyond the end of the accuracy interval, clear of every whisker.
        above = path in ('1L', '5')
        ax.annotate(
            f'{_label(path, vm["nova_model"])}\n{100 * y:.0f}%, ${x:.3f}/q',
            (x, ahi if above else alo),
            xytext=(0, 4 if above else -4),
            textcoords='offset points',
            ha='center',
            va='bottom' if above else 'top',
            fontsize=7.5,
            color=INK,
        )
    ax.set_xscale('log')
    ax.margins(y=0.2)
    ax.set_xlabel('Mean list-price cost per question, USD (log; 95% video-bootstrap interval)')
    ax.set_ylabel('Accuracy (95% video-cluster bootstrap interval)')
    ax.grid(True, color=GRID, lw=0.6, which='major')
    ax.set_axisbelow(True)
    ax.set_title('Video-MME: accuracy against cost per question', loc='left')
    fig.tight_layout()
    fig.savefig(out, dpi=200, bbox_inches='tight')
    plt.close(fig)


def cost_fits(vm: dict) -> dict:
    """Least-squares list-price cost per question = intercept + slope * duration, per path."""
    import numpy as np

    fits = {}
    for path in ('1', '1L', '2'):
        key = f'p{path.lower()}_list_cost'
        pts = [
            (r['duration_sec'], r[key])
            for r in vm['predictions']
            if r.get(key) and r['duration_sec']
        ]
        if len(pts) < 3:
            continue
        xs, ys = np.array(pts).T
        slope, intercept = np.polyfit(xs, ys, 1)
        residual = np.sum((ys - (slope * xs + intercept)) ** 2)
        fits[path] = {
            'micro_usd_per_sec': float(slope * 1e6),
            'intercept_usd': float(intercept),
            'r2': float(1 - residual / np.sum((ys - ys.mean()) ** 2)),
            'n': len(pts),
        }
    return fits


def fig_videomme_cost_duration(vm: dict, fits: dict, out: Path) -> None:
    rows = vm['predictions']
    fig, ax = plt.subplots(figsize=(6.5, 3.2))
    # Nova samples at most 960 frames, so its cost stops growing past 16 minutes: points, no fit.
    for path in ('1', '1L', '2', '5'):
        key = f'p{path.lower()}_list_cost'
        points = [
            (r['duration_sec'] / 60, r[key])
            for r in rows
            if r.get(key) and r['duration_sec'] and r.get(f'p{path.lower()}_attempted', True)
        ]
        if not points:
            continue
        xs, ys = zip(*points)
        ax.scatter(
            xs,
            ys,
            s=14,
            marker=PATH_MARKER[path],
            color=PATH_COLOR[path],
            edgecolors=SURFACE,
            linewidths=0.6,
            label=_label(path, vm['nova_model']),
            alpha=0.9,
        )
        if path in fits:
            grid = sorted(xs)
            fit = fits[path]
            line = [fit['intercept_usd'] + fit['micro_usd_per_sec'] * 60e-6 * m for m in grid]
            ax.plot(grid, line, color=PATH_COLOR[path], lw=1, alpha=0.8)
    ax.set_xscale('log')
    ax.set_yscale('log')
    ax.set_xlabel('Video length, minutes (log)')
    ax.set_ylabel('List-price cost per question, USD (log)')
    ax.grid(True, color=GRID, lw=0.6)
    ax.set_axisbelow(True)
    ax.legend(fontsize=8, loc='upper left')
    ax.set_title('Cost per question grows with video length', loc='left')
    fig.tight_layout()
    fig.savefig(out, dpi=200, bbox_inches='tight')
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--pursuit',
        type=Path,
        nargs='+',
        default=[
            ROOT / 'results' / 'paper' / 'pursuit',
            ROOT / 'results' / 'paper' / 'pursuit-all',
        ],
        help='Directories of exported Pursuit runs (all runs are pooled per path)',
    )
    parser.add_argument('--videomme', type=Path, default=None)
    args = parser.parse_args()
    FIGURES.mkdir(parents=True, exist_ok=True)
    numbers: dict = {'path_labels': PATH_LABELS, 'clip_check_count': len(CLIP_CHECKS)}
    pursuit_dirs = [d for d in args.pursuit if d.exists()]
    if pursuit_dirs:
        numbers['pursuit'] = pursuit_numbers(pursuit_dirs)
        fig_pursuit_breakdown(numbers['pursuit'], FIGURES / 'pursuit_cost_breakdown.png')
    vm_dir = args.videomme or (ROOT / 'results' / 'paper' / 'videomme')
    if vm_dir.exists() and not (vm_dir / 'summary.json').exists():
        vm_dir = _latest(vm_dir)
    if (vm_dir / 'summary.json').exists():
        vm = videomme_numbers(vm_dir)
        numbers['videomme'] = {'run': vm_dir.name, 'nova_model': vm['nova_model'], **vm['summary']}
        fig_videomme_accuracy(vm, FIGURES / 'videomme_accuracy.png')
        fig_videomme_cost_accuracy(vm, FIGURES / 'videomme_cost_accuracy.png')
        numbers['videomme']['cost_fits'] = cost_fits(vm)
        numbers['videomme']['answered_by_all_gemini'] = answered_comparison(vm)
        if V1_VIDEOMME.exists():
            numbers['videomme']['v1_same_questions'] = v1_comparison(vm)
        fig_videomme_cost_duration(
            vm, numbers['videomme']['cost_fits'], FIGURES / 'videomme_cost_duration.png'
        )
    NUMBERS.write_text(json.dumps(numbers, indent=2, default=str) + '\n')
    for path in sorted(FIGURES.glob('*.png')):
        print(f'{path.relative_to(ROOT)} ({path.stat().st_size // 1024} KB)')
    print(NUMBERS.relative_to(ROOT))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
