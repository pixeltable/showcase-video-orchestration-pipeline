"""Video-MME multiple-choice evaluation (Paths 1, 1L, 2, 3, 5; default 1 and 2)."""

from __future__ import annotations

__all__ = ['DEFAULT_N', 'DEFAULT_SEED', 'VIDEOME_ASSETS']

from video_benchmark.config import ASSETS_DIR

DEFAULT_N = 30
DEFAULT_SEED = 42
VIDEOME_ASSETS = ASSETS_DIR / 'videomme'
MANIFEST_NAME = 'sample_manifest.json'
