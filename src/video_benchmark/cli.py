"""CLI: run-benchmark. One video, one question, the selected paths."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from video_benchmark import admission
from video_benchmark import config as configuration
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
    admission.add_arguments(parser)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        configuration.load_dotenv()
        paths = parse_paths(args.paths or os.environ.get('BENCHMARK_PATHS'))
        paths = apply_skip_flags(
            paths, skip_oss=args.skip_oss, skip_fal=args.skip_fal, skip_nova=args.skip_nova
        )
        config = load_config(paths)
        admission.validate_arguments(args)
    except ValueError as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 1
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
    query = args.query or config.default_query
    if len(query) > 4000 or config.vision_sample_keyframes > 64:
        print(
            'Error: query must fit 4000 characters and frame preparation must fit 64 frames.',
            file=sys.stderr,
        )
        return 1
    try:
        video_path = ensure_sample_video(Path(args.video) if args.video else None)
        seconds = admission.inspect_media(
            [str(video_path)],
            max_seconds=args.max_media_seconds,
            require_audio=plan_paths(config, paths).modular,
        )
    except (OSError, ValueError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 1

    if args.preflight:
        print(
            json.dumps(
                {
                    'paths': plan_paths(config, paths).enabled(),
                    'maximum_duration_sec': seconds,
                    'budget_usd': args.budget_usd,
                    'max_attempts': args.max_attempts,
                    'model_output_cap_tokens': admission.MAX_OUTPUT_TOKENS,
                    'provider_access': 'not tested; credentials configured',
                },
                indent=2,
            )
        )
        return 0

    export_base = Path(args.export) if args.export else PROJECT_ROOT / 'results'
    any_failed = False
    ledger = admission.AttemptLedger(
        Path(args.ledger) if args.ledger else PROJECT_ROOT / 'results' / 'provider-ledger.sqlite3',
        budget_usd=args.budget_usd,
        max_attempts=args.max_attempts,
    )
    try:
        with admission.provider_session(
            ledger, seconds=seconds, bedrock_enabled=plan_paths(config, paths).nova
        ):
            if args.reset:
                print('Dropping the video_benchmarking catalog ...')
                reset_catalog()
            plan = apply_schema(config, paths)
            for _ in range(args.repeats):
                run_id, failed = run_benchmark(plan, video_path, query)
                any_failed = any_failed or bool(failed)
                out = export_run(run_id, plan, config, video_path, export_base)
                admission.export_snapshot(ledger, out)
                print((out / 'REPORT.md').read_text())
                print(f'Exported {out}; durable attempt ledger: {ledger.path}')
    except (CatalogSchemaMismatch, admission.AdmissionError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 1
    return 1 if any_failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
