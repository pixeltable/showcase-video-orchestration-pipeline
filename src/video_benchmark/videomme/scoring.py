"""MCQ letter extraction and exact-match scoring."""

from __future__ import annotations

import re

import pixeltable as pxt

_ANSWER_LINE = re.compile(r'(?:^|\n)\s*(?:final\s+)?answer\s*[:\-]\s*\**([A-D])\b', re.IGNORECASE)
_BOXED = re.compile(r'\\boxed\{\s*([A-D])\s*\}', re.IGNORECASE)
_THE_ANSWER_IS = re.compile(
    r'(?:the\s+)?(?:correct\s+)?answer\s+is\s*[:\-]?\s*\**([A-D])\b', re.IGNORECASE
)
_BARE_LETTER = re.compile(r'\b([A-D])\b')
_ANSWER_NONE = re.compile(r'(?:^|\n)\s*(?:final\s+)?answer\s*[:\-]\s*none\b', re.IGNORECASE)


def extract_letter_impl(text: str) -> str | None:
    """The chosen option: the last explicit 'Answer: X' / boxed / 'the answer is X', else a
    lone letter on the last line."""
    raw = (text or '').strip()
    if not raw or _ANSWER_NONE.search(raw):
        return None
    for pattern in (_ANSWER_LINE, _BOXED, _THE_ANSWER_IS):
        matches = list(pattern.finditer(raw))
        if matches:
            return matches[-1].group(1).upper()
    letters = _BARE_LETTER.findall(raw.splitlines()[-1])
    return letters[0].upper() if len(letters) == 1 else None


def is_correct_impl(letter: str | None, gold: str) -> bool:
    return bool(letter) and letter.strip().upper()[:1] == gold.strip().upper()[:1]


def window_text_impl(text: str, max_chars: int) -> str:
    """Fit text into `max_chars` for a small-context local model: keep the first 20%, a
    middle 40%, and the last 40%, so late-video evidence survives."""
    if len(text) <= max_chars:
        return text
    mid_marker, tail_marker = '\n...[middle]...\n', '\n...[end]...\n'
    budget = max(0, max_chars - len(mid_marker) - len(tail_marker))
    head_n, mid_n = int(budget * 0.2), int(budget * 0.4)
    tail_n = budget - head_n - mid_n
    mid_start = (len(text) - mid_n) // 2
    return (
        f'{text[:head_n]}{mid_marker}{text[mid_start : mid_start + mid_n]}{tail_marker}'
        f'{text[len(text) - tail_n :]}'
    )


@pxt.udf
def extract_letter(text: str | None) -> str | None:
    return extract_letter_impl(text or '')


@pxt.udf
def is_correct(letter: str | None, gold: str) -> bool:
    return is_correct_impl(letter, gold)


@pxt.udf
def window_text(text: str, max_chars: int) -> str:
    return window_text_impl(text, max_chars)
