"""Path selection for the Pursuit benchmark CLI (mirrors Video-MME --paths)."""

from __future__ import annotations

ALL_PATHS = frozenset({'1', '2', '3', '4', '5'})
# Showcase default: Gemini native vs orchestrated (OSS/fal/Nova opt-in).
DEFAULT_PATHS = frozenset({'1', '2'})


def parse_paths(raw: str | None) -> set[str]:
    if not raw or not str(raw).strip():
        return set(DEFAULT_PATHS)
    parts = {p.strip() for p in str(raw).split(',') if p.strip()}
    unknown = parts - ALL_PATHS
    if unknown:
        raise ValueError(f'Unknown paths {unknown}; use subset of 1,2,3,4,5')
    return parts


def apply_skip_flags(
    paths: set[str],
    *,
    skip_oss: bool = False,
    skip_fal: bool = False,
    skip_nova: bool = False,
) -> set[str]:
    out = set(paths)
    if skip_oss:
        out.discard('3')
    if skip_fal:
        out.discard('4')
    if skip_nova:
        out.discard('5')
    return out
