"""CLI: run-videomme-dev — stratified Video-MME Paths 1,2,3,5."""

from __future__ import annotations

import argparse
import os
import sys

from video_benchmark.config import PROJECT_ROOT, load_config, load_dotenv
from video_benchmark.videomme import DEFAULT_N, DEFAULT_SEED
from video_benchmark.videomme.export import export_run
from video_benchmark.videomme.runner import parse_paths, run_videomme_dev


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            'Video-MME dev slice: stratified MCQs — Gemini Paths 1–2, '
            'Path 3 OSS, Path 5 Nova (fal omitted)'
        )
    )
    p.add_argument('--n', type=int, default=None, help='Number of questions (default 30)')
    p.add_argument('--seed', type=int, default=None, help='Sampling seed (default 42)')
    p.add_argument(
        '--reset',
        action='store_true',
        help='Drop and recreate the videomme/ Pixeltable catalog',
    )
    p.add_argument(
        '--fresh-sample',
        action='store_true',
        help='Ignore existing sample_manifest.json and resample',
    )
    p.add_argument(
        '--export',
        type=str,
        default=None,
        help='Export base directory (default: results/videomme-dev)',
    )
    p.add_argument(
        '--sample-only',
        action='store_true',
        help='Only sample + download; do not call models',
    )
    p.add_argument(
        '--paths',
        type=str,
        default=None,
        help='Comma-separated paths to run: 1,2,3,5 (default all)',
    )
    p.add_argument('--skip-oss', action='store_true', help='Skip Path 3 OSS')
    p.add_argument('--skip-nova', action='store_true', help='Skip Path 5 Nova')
    return p.parse_args()


def main() -> int:
    load_dotenv()
    args = parse_args()
    n = int(args.n or os.environ.get('VIDEOME_DEV_N', DEFAULT_N))
    seed = int(args.seed or os.environ.get('VIDEOME_DEV_SEED', DEFAULT_SEED))

    try:
        paths = parse_paths(args.paths or os.environ.get('VIDEOME_PATHS'))
    except ValueError as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 1
    if args.skip_oss:
        paths.discard('3')
    if args.skip_nova:
        paths.discard('5')

    need_gemini = bool(paths & {'1', '2'})
    if need_gemini and not (
        os.environ.get('GOOGLE_API_KEY') or os.environ.get('GEMINI_API_KEY')
    ):
        if not args.sample_only:
            print(
                'Error: set GOOGLE_API_KEY or GEMINI_API_KEY for Gemini Paths 1–2.',
                file=sys.stderr,
            )
            return 1

    config = load_config()

    if args.sample_only:
        from video_benchmark.videomme.runner import prepare_sample_and_downloads

        qs, downloads = prepare_sample_and_downloads(
            n=n, seed=seed, reuse_manifest=not args.fresh_sample
        )
        print(f'Sampled {len(qs)} questions across {len(downloads)} videos (sample-only).')
        return 0

    print(f'Running Video-MME paths={sorted(paths)}', flush=True)
    predictions, video_shared, cfg = run_videomme_dev(
        n=n,
        seed=seed,
        reset=args.reset,
        reuse_manifest=not args.fresh_sample,
        config=config,
        paths=paths,
    )
    export_base = (
        PROJECT_ROOT / args.export
        if args.export
        else PROJECT_ROOT / 'results' / 'videomme-dev'
    )
    out = export_run(
        predictions=predictions,
        video_shared=video_shared,
        config=cfg,
        seed=seed,
        n=n,
        export_base=export_base,
        paths=paths,
    )
    print(f'\nExported Video-MME dev results to {out}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
