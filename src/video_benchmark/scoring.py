"""Insight quality heuristics.

Sample-only checks (nice_pants, jay, salary, tonight) are tuned to the Pursuit of
Happyness clip for continuity across exports — not general success criteria.

General checks (truncated, has_sections, no_per_frame_spam, complete) apply to any video.
"""

from __future__ import annotations

import re

_SECTION_MARKERS = ('main activities', 'speakers', 'visual events')
_TRAILING_JUNK = re.compile(r'(.)\1{4,}\s*$')  # e.g. "toneeeee" / "....."
_MID_SENTENCE_END = re.compile(r'[a-z0-9,;:]\s*$')
_PER_FRAME_TS = re.compile(
    r'\bat\s+\d+(?:\.\d+)?\s*(?:seconds?|s)\b',
    re.IGNORECASE,
)


def _has_salary(lower: str) -> bool:
    if 'salary' in lower or 'no salary' in lower:
        return True
    if 'unpaid internship' in lower:
        return True
    return False


def _looks_truncated(text: str) -> bool:
    stripped = (text or '').rstrip()
    if not stripped:
        return True
    if _TRAILING_JUNK.search(stripped):
        return True
    # Ends mid-sentence without terminal punctuation (ignore short stubs).
    if len(stripped.split()) > 40 and _MID_SENTENCE_END.search(stripped):
        if not stripped.endswith(('.', '!', '?', '"', "'", ')', ']')):
            return True
    return False


def _has_sections(lower: str) -> bool:
    return all(marker in lower for marker in _SECTION_MARKERS)


def _no_per_frame_spam(lower: str) -> bool:
    """True when the answer is not a per-timestamp inventory."""
    return len(_PER_FRAME_TS.findall(lower)) <= 2


def score_insight_text(text: str) -> dict[str, bool]:
    """Score a path insight for general quality and sample-only dialogue signals."""
    raw = text or ''
    lower = raw.lower()
    return {
        # Sample-only (Pursuit continuity)
        'nice_pants': 'nice pants' in lower or 'really nice pants' in lower,
        'jay_named': 'jay' in lower,
        'chris_named': 'chris' in lower or 'will smith' in lower,
        'has_salary': _has_salary(lower),
        'has_tonight': 'tonight' in lower,
        # General
        'complete': not _looks_truncated(raw) and len(raw.split()) > 200,
        'truncated': _looks_truncated(raw),
        'has_sections': _has_sections(lower),
        'no_per_frame_spam': _no_per_frame_spam(lower),
    }
