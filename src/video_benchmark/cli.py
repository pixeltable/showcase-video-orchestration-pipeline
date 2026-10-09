"""CLI: run-benchmark. One video, one question, the selected paths."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from video_benchmark.config import PROJECT_ROOT, load_config
from video_benchmark.paths import PATH_LABELS, apply_skip_flags, parse_paths
from video_benchmark.reporting import export_run
from video_benchmark.runner import ensure_sample_video, run_benchmark
from video_benchmark.schema import CatalogSchemaMismatch, apply_schema, plan_paths, reset_catalog


def parse_args() -> argparse.Namespace:
    paths_help = '; '.join(f'{p}={label}' for p, label in PATH_LABELS.items())
    parser = argparse.ArgumentParser(
        description=(
            'Answer one question about one video with native and orchestrated paths, '
            'declared as a Pixeltable TableModel graph.'
        )
    )
    parser.add_argument(
        '--video', type=str, default=None, help='Input video (default: Pursuit clip)'
    )
    parser.add_argument('--query', type=str, default=None, help='Question about the video')
    parser.add_argument(
        '--paths', type=str, default=None, help=f'Comma-separated, default 1,2 ({paths_help})'
    )
    parser.add_argument(
        '--reset',
        action='store_true',
        help='Drop and rebuild the catalog (needed when --paths or settings change)',
    )
    parser.add_argument('--repeats', type=int, default=1, help='Independent runs to execute')
    parser.add_argument(
        '--export', type=str, default=None, metavar='DIR', help='Export base (default: results/)'
    )
    parser.add_argument('--skip-oss', action='store_true', help='Drop Path 3')
    parser.add_argument('--skip-fal', action='store_true', help='Drop Path 4')
    parser.add_argument('--skip-nova', action='store_true', help='Drop Path 5')
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        config = load_config()
        paths = parse_paths(args.paths or os.environ.get('BENCHMARK_PATHS'))
    except ValueError as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 1
    paths = apply_skip_flags(
        paths, skip_oss=args.skip_oss, skip_fal=args.skip_fal, skip_nova=args.skip_nova
    )
    if not paths:
        print('Error: no paths selected after --skip-* flags.', file=sys.stderr)
        return 1
    if args.repeats < 1:
        print('Error: --repeats must be at least 1.', file=sys.stderr)
        return 1
    needs_gemini = bool(paths & {'1', '1L', '2'}) or ('3' in paths and config.oss_asr == 'gemini')
    if needs_gemini and not (os.environ.get('GOOGLE_API_KEY') or os.environ.get('GEMINI_API_KEY')):
        print('Error: set GOOGLE_API_KEY or GEMINI_API_KEY for the Gemini paths.', file=sys.stderr)
        return 1
    if '4' in paths and not config.enable_fal:
        print('Skipping Path 4: set FAL_KEY (and pip install -e ".[fal]").', file=sys.stderr)
    if '5' in paths and not config.enable_nova:
        print('Skipping Path 5: set AWS or Bedrock credentials.', file=sys.stderr)
    if '3' in paths and config.oss_asr == 'whisper' and os.environ.get('OSS_ASR') != 'whisper':
        print('Path 3 uses Whisper: WhisperX diarization needs HF_TOKEN.', file=sys.stderr)
    if not plan_paths(config, paths).enabled():
        print('Error: none of the selected paths have credentials.', file=sys.stderr)
        return 1
    try:
        video_path = ensure_sample_video(Path(args.video) if args.video else None)
    except (OSError, ValueError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 1

    if args.reset:
        print('Dropping the video_benchmarking catalog ...')
        reset_catalog()
    try:
        plan = apply_schema(config, paths)
    except CatalogSchemaMismatch as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 1

    query = args.query or config.default_query
    export_base = Path(args.export) if args.export else PROJECT_ROOT / 'results'
    any_failed = False
    for _ in range(args.repeats):
        run_id, failed = run_benchmark(plan, video_path, query)
        any_failed = any_failed or bool(failed)
        out = export_run(run_id, plan, config, video_path, export_base)
        print((out / 'REPORT.md').read_text())
        print(f'Exported {out}')
    return 1 if any_failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
