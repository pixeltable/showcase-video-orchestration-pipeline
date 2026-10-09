"""CLI: run-videomme. A duration-stratified Video-MME sample, scored per path."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from video_benchmark import config as configuration
from video_benchmark.config import PROJECT_ROOT, load_config
from video_benchmark.paths import PATH_LABELS
from video_benchmark.schema import CatalogSchemaMismatch, plan_paths
from video_benchmark.videomme import DEFAULT_N, DEFAULT_SEED
from video_benchmark.videomme.export import export_run
from video_benchmark.videomme.runner import (
    ALLOWED_PATHS,
    InputConflict,
    parse_paths,
    prepare_sample,
    run_videomme,
)
from video_benchmark.videomme.schema import reset_catalog


def parse_args() -> argparse.Namespace:
    paths_help = '; '.join(f'{p}={PATH_LABELS[p]}' for p in sorted(ALLOWED_PATHS))
    p = argparse.ArgumentParser(
        description='Video-MME multiple-choice accuracy and cost per path (Pixeltable catalog).'
    )
    p.add_argument('--n', type=int, default=None, help=f'Questions to sample (default {DEFAULT_N})')
    p.add_argument('--seed', type=int, default=None, help=f'Sampling seed (default {DEFAULT_SEED})')
    p.add_argument('--paths', type=str, default=None, help=f'Default 1,2 ({paths_help})')
    p.add_argument('--reset', action='store_true', help='Drop and rebuild the videomme catalog')
    p.add_argument('--fresh-sample', action='store_true', help='Ignore the saved sample manifest')
    p.add_argument(
        '--local-only', action='store_true', help='Sample only among already-downloaded videos'
    )
    p.add_argument('--sample-only', action='store_true', help='Sample and download; no model calls')
    p.add_argument(
        '--export', type=str, default=None, help='Export base (default results/videomme)'
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    try:
        configuration.load_dotenv()
        paths = parse_paths(args.paths or os.environ.get('VIDEOME_PATHS'))
        config = load_config(paths, videomme=True)
        n = args.n if args.n is not None else int(os.environ.get('VIDEOME_N', DEFAULT_N))
        seed = (
            args.seed if args.seed is not None
            else int(os.environ.get('VIDEOME_SEED', DEFAULT_SEED))
        )
    except ValueError as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 1
    if n < 1:
        print('Error: --n must be at least 1.', file=sys.stderr)
        return 1
    if not args.sample_only and paths & {'1', '1L', '2', '3'} and not (
        os.environ.get('GOOGLE_API_KEY') or os.environ.get('GEMINI_API_KEY')
    ):
        print(
            'Error: set GOOGLE_API_KEY or GEMINI_API_KEY (Path 3 shares Gemini ASR).',
            file=sys.stderr,
        )
        return 1
    if '5' in paths and not config.enable_nova:
        print('Skipping Path 5: set AWS or Bedrock credentials.', file=sys.stderr)
    if not args.sample_only and not plan_paths(config, paths).enabled():
        print('Error: none of the selected paths have credentials.', file=sys.stderr)
        return 1
    questions, downloads = prepare_sample(
        n=n, seed=seed, reuse_manifest=not args.fresh_sample, local_only=args.local_only
    )
    if args.sample_only:
        return 0
    if args.reset:
        reset_catalog()
    try:
        predictions, videos = run_videomme(config, paths, questions, downloads)
    except (CatalogSchemaMismatch, InputConflict) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 1
    export_base = Path(args.export) if args.export else PROJECT_ROOT / 'results' / 'videomme'
    out = export_run(
        predictions=predictions,
        videos=videos,
        paths=plan_paths(config, paths).enabled(),
        config=config,
        seed=seed,
        n=n,
        export_base=export_base,
    )
    print((out / 'REPORT.md').read_text())
    print(f'Exported {out}')
    return int(any(
        record.get(f'p{path.lower()}_error') or record.get(f'p{path.lower()}_accounting_error')
        for record in predictions for path in plan_paths(config, paths).enabled()
    ))


if __name__ == '__main__':
    raise SystemExit(main())
