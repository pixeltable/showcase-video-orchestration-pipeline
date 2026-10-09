"""Run one benchmark: insert the run, then its synthesis request. Pixeltable computes the rest."""

from __future__ import annotations

import sys
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pixeltable as pxt

from video_benchmark.config import DEFAULT_SAMPLE, PURSUIT_VIDEO_URL
from video_benchmark.schema import CATALOG_DIR, PathPlan


def ensure_sample_video(video_path: Path | None = None) -> str:
    if video_path is not None:
        path = video_path.expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f'Video not found: {path}')
        return str(path)
    if not DEFAULT_SAMPLE.exists():
        DEFAULT_SAMPLE.parent.mkdir(parents=True, exist_ok=True)
        print(f'Downloading sample video to {DEFAULT_SAMPLE} ...')
        urllib.request.urlretrieve(PURSUIT_VIDEO_URL, DEFAULT_SAMPLE)
    return str(DEFAULT_SAMPLE.resolve())


def new_run_id() -> str:
    return f'{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:6]}'


def table(name: str) -> pxt.Table:
    return pxt.get_table(f'{CATALOG_DIR}.{name}')


def _insert(tbl: pxt.Table, row: dict) -> list[str]:
    """Insert one row, recording failed cells instead of aborting; return failed columns."""
    status = tbl.insert([row], on_error='ignore')
    return list(status.cols_with_excs or [])


def retry_failed(failed: list[str], run_id: str) -> list[str]:
    """Recompute each failed cell of this run once (downstream columns follow).

    Pixeltable already retries rate-limit errors; this covers other transient provider errors.
    """
    still_failed = []
    for qualified in failed:
        # Insert status names columns '<table>.<column>' without the catalog directory.
        tbl_name, _, column = qualified.rpartition('.')
        tbl = table(tbl_name.rsplit('/', 1)[-1])
        if retry_column_once(tbl, column, tbl.run_id == run_id):
            still_failed.append(qualified)
    return still_failed


def retry_column_once(tbl: pxt.Table, column: str, scope) -> int:
    """Retry transient failures, preserving schema/parsing/dependency errors for inspection.

    In particular a blocked Gemini response currently fails inside the SDK with TypeError;
    calling the provider again does not recover its lost response metadata.
    """
    col = getattr(tbl, column)
    permanent = col.errortype.isin(
        ['TypeError', 'ValueError', 'ImportError', 'ModuleNotFoundError']
    )
    tbl.recompute_columns(column, where=scope & ~permanent, errors_only=True)
    return sum(bool(row['error']) for row in tbl.where(scope).select(error=col.errormsg).collect())


def run_benchmark(plan: PathPlan, video_path: str, query: str) -> tuple[str, list[str]]:
    """Returns the run id and the columns that still failed after one retry."""
    run_id = new_run_id()
    row = {'run_id': run_id, 'video': video_path, 'query': query}
    print(f'Run {run_id}: paths {",".join(sorted(plan.active))}')
    failed = retry_failed(_insert(table('runs'), row), run_id)
    # The synthesis row goes in after the run's keyframes and transcript exist.
    if plan.modular:
        failed += retry_failed(_insert(table('syntheses'), row), run_id)
    for column in failed:
        print(f'Failed after retry: {column} (see {column}.errormsg)', file=sys.stderr)
    return run_id, failed
