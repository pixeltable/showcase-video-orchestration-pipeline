"""Path selection shared by the Pursuit and Video-MME CLIs."""

from __future__ import annotations

PATH_LABELS = {
    '1': 'Native Gemini (full video)',
    '1L': 'Native Gemini, low media resolution',
    '2': 'Orchestrated Gemini (keyframes + ASR + synthesis)',
    '3': 'Open-source local stack (keyframes + ASR + synthesis)',
    '4': 'Native fal video-understanding (first 120 s)',
    '5': 'Native Amazon Nova (Bedrock)',
}
ALL_PATHS = frozenset(PATH_LABELS)
# Showcase default: the same Gemini model, native vs orchestrated.
DEFAULT_PATHS = frozenset({'1', '2'})


def parse_paths(
    raw: str | None,
    *,
    allowed: frozenset[str] = ALL_PATHS,
    default: frozenset[str] = DEFAULT_PATHS,
) -> set[str]:
    if not raw or not raw.strip():
        return set(default)
    parts = {p.strip().upper() for p in raw.split(',') if p.strip()}
    unknown = parts - allowed
    if unknown:
        raise ValueError(
            f'Unknown paths {sorted(unknown)}; use a subset of {",".join(sorted(allowed))}'
        )
    return parts


def apply_skip_flags(
    paths: set[str], *, skip_oss: bool = False, skip_fal: bool = False, skip_nova: bool = False
) -> set[str]:
    skipped = {p for p, skip in (('3', skip_oss), ('4', skip_fal), ('5', skip_nova)) if skip}
    return set(paths) - skipped
