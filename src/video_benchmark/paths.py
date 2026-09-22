"""Path selection for the Pursuit benchmark CLI (mirrors Video-MME --paths)."""

from __future__ import annotations

ALL_PATHS = frozenset({'1', '2', '3', '4', '5'})
# Showcase default: Gemini native vs orchestrated (OSS/fal/Nova opt-in).
DEFAULT_PATHS = frozenset({'1', '2'})


def parse_paths(
    raw: str | None,
    *,
    allowed: frozenset[str] = ALL_PATHS,
    default: frozenset[str] | None = None,
) -> set[str]:
    default_paths = set(default if default is not None else DEFAULT_PATHS)
    if not raw or not str(raw).strip():
        return default_paths
    parts = {p.strip() for p in str(raw).split(',') if p.strip()}
    unknown = parts - set(allowed)
    if unknown:
        allowed_label = ','.join(sorted(allowed))
        raise ValueError(f'Unknown paths {unknown}; use subset of {allowed_label}')
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
