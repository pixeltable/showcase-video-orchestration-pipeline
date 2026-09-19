"""CLI entry point for the video understanding benchmark."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from video_benchmark.config import PROJECT_ROOT, load_config
from video_benchmark.paths import apply_skip_flags, parse_paths
from video_benchmark.pipeline import setup_pipeline
from video_benchmark.reporting import (
    build_comparison_dataframe,
    export_run,
    print_three_way_comparison,
)
from video_benchmark.runner import ensure_sample_video, reset_catalog, run_benchmark


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            'Pixeltable video understanding benchmark '
            '(native Gemini vs modular vs OSS; optional fal/Nova)'
        )
    )
    parser.add_argument('--video', type=str, default=None, help='Path to input video file')
    parser.add_argument('--query', type=str, default=None, help='Analysis question')
    parser.add_argument(
        '--reset',
        action='store_true',
        help='Drop and recreate the video_benchmarking catalog',
    )
    parser.add_argument(
        '--export',
        type=str,
        default=None,
        metavar='DIR',
        help='Export results to DIR/<timestamp>/ (default: results/)',
    )
    parser.add_argument(
        '--paths',
        type=str,
        default=None,
        help='Comma-separated paths: 1,2,3,4,5 (default 1,2)',
    )
    parser.add_argument('--skip-oss', action='store_true', help='Skip Path 3 OSS')
    parser.add_argument('--skip-fal', action='store_true', help='Skip Path 4 fal')
    parser.add_argument('--skip-nova', action='store_true', help='Skip Path 5 Nova')
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config()

    try:
        paths = parse_paths(args.paths or os.environ.get('BENCHMARK_PATHS'))
    except ValueError as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 1
    paths = apply_skip_flags(
        paths,
        skip_oss=args.skip_oss,
        skip_fal=args.skip_fal,
        skip_nova=args.skip_nova,
    )
    if not paths:
        print('Error: no paths selected after --skip-* flags.', file=sys.stderr)
        return 1

    need_gemini = bool(paths & {'1', '2'}) or (
        '3' in paths and config.oss_asr == 'gemini'
    )
    if need_gemini and not (
        os.environ.get('GOOGLE_API_KEY') or os.environ.get('GEMINI_API_KEY')
    ):
        print(
            'Error: set GOOGLE_API_KEY or GEMINI_API_KEY for Gemini paths '
            '(native, orchestrated, or OSS_ASR=gemini).',
            file=sys.stderr,
        )
        return 1

    if config.benchmark_reset or args.reset:
        reset_catalog()

    print(f'Setting up catalog for paths={",".join(sorted(paths))}', flush=True)
    setup_pipeline(config, paths=paths)

    video_path = ensure_sample_video(Path(args.video) if args.video else None)
    query = args.query or config.default_query

    run_benchmark(config, video_path, query, paths=paths)
    print_three_way_comparison(config)

    export_base = Path(args.export) if args.export else PROJECT_ROOT / 'results'
    out_dir = export_run(config, export_base, video_path, query)
    print(f'\nExported results to {out_dir}')

    if pipeline_has_keyframes():
        comparison_df = build_comparison_dataframe()
        print('\n=== Frame-level: Gemini vs OSS-VLM per keyframe ===')
        print(comparison_df.to_string(index=False))
    return 0


def pipeline_has_keyframes() -> bool:
    from video_benchmark import pipeline

    return pipeline.keyframes is not None


if __name__ == '__main__':
    raise SystemExit(main())
