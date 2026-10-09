"""Answer heuristics for the Pursuit clip.

The clip checks (nice_pants, jay, chris, salary, tonight) test for specific beats of the
Pursuit of Happyness interview; they say nothing about other videos. The general checks
(complete, truncated, sections, no_spam) apply to any answer. Both are diagnostics, not a
quality metric: Video-MME accuracy is the quantitative evaluation.
"""

from __future__ import annotations

import re

_SECTION_MARKERS = ('main activities', 'speakers', 'visual events')
_TRAILING_JUNK = re.compile(r'(.)\1{4,}\s*$')  # e.g. "toneeeee" / "....."
_MID_SENTENCE_END = re.compile(r'[a-z0-9,;:]\s*$')
_PER_FRAME_TS = re.compile(r'\bat\s+\d+(?:\.\d+)?\s*(?:seconds?|s)\b', re.IGNORECASE)


def _looks_truncated(text: str) -> bool:
    stripped = text.rstrip()
    if not stripped or _TRAILING_JUNK.search(stripped):
        return True
    # A long answer that ends mid-sentence was cut off.
    return len(stripped.split()) > 40 and bool(_MID_SENTENCE_END.search(stripped))


def score_answer(text: str) -> dict[str, bool]:
    lower = text.lower()
    truncated = _looks_truncated(text)
    return {
        'nice_pants': 'nice pants' in lower,
        'jay': 'jay' in lower,
        'chris': 'chris' in lower or 'will smith' in lower,
        'salary': 'salary' in lower or 'unpaid internship' in lower,
        'tonight': 'tonight' in lower,
        'complete': not truncated and len(text.split()) > 200,
        'truncated': truncated,
        'sections': all(marker in lower for marker in _SECTION_MARKERS),
        'no_spam': len(_PER_FRAME_TS.findall(lower)) <= 2,
    }


CLIP_CHECKS = ('nice_pants', 'jay', 'chris', 'salary', 'tonight')
GENERAL_CHECKS = ('complete', 'truncated', 'sections', 'no_spam')
