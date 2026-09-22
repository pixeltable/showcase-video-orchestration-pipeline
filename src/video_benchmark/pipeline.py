"""Apply the Pursuit TableModel catalog and bind table globals."""

from __future__ import annotations

import pixeltable as pxt

from video_benchmark.config import BenchmarkConfig
from video_benchmark.paths import DEFAULT_PATHS
from video_benchmark.schema import CATALOG_DIR, apply_pursuit_schema

video_sources: pxt.Table | None = None
keyframes: pxt.Table | None = None
audio_chunks: pxt.Table | None = None


def clear_handles() -> None:
    global video_sources, keyframes, audio_chunks
    video_sources = None
    keyframes = None
    audio_chunks = None


def setup_pipeline(
    config: BenchmarkConfig,
    paths: set[str] | None = None,
) -> None:
    global video_sources, keyframes, audio_chunks

    active = set(paths) if paths is not None else set(DEFAULT_PATHS)
    apply_pursuit_schema(config, active)

    video_sources = pxt.get_table(f'{CATALOG_DIR}.video_sources')
    keyframes = pxt.get_table(f'{CATALOG_DIR}.keyframes', if_not_exists='ignore')
    audio_chunks = pxt.get_table(f'{CATALOG_DIR}.audio_chunks', if_not_exists='ignore')
