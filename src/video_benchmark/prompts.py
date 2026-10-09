"""Prompts. Every path that writes the final answer receives the same task instructions.

Native paths (1, 1L, 4, 5) see the video; orchestrated paths (2, 3) see evidence extracted
from it. Only that difference is under test, so the question and the answer guidance are
shared word for word.
"""

from __future__ import annotations

import pixeltable as pxt

ANSWER_GUIDANCE = (
    'Cover the whole video from beginning to end. Name or label each speaker, quote the key '
    'lines of dialogue, and describe the main visual events in order.'
)

TRANSCRIBE_PROMPT = (
    'Transcribe this audio with timestamps and speaker labels. '
    'Return one line per utterance in this format:\n'
    '[mm:ss] Speaker N: spoken text\n'
    'Use Speaker 1, Speaker 2, etc. Do not include any other commentary.'
)


def native_prompt_impl(query: str) -> str:
    return f'Analyze this video and answer the question.\n\nQuestion: {query}\n\n{ANSWER_GUIDANCE}'


def synthesis_prompt_impl(query: str, evidence: str, duration_sec: float, n_images: int = 0) -> str:
    images = f' {n_images} of the keyframes are attached as images above.' if n_images else ''
    return (
        f'The evidence below was extracted from a video about {duration_sec:.0f} seconds long: '
        'a timestamped audio transcript and descriptions of keyframes sampled across the whole '
        f'video.{images} Treat it as your view of the video and answer the question.\n\n'
        f'Question: {query}\n\n{ANSWER_GUIDANCE} Write a narrative answer instead of repeating '
        'the keyframe log line by line, and do not comment on the evidence itself.\n\n'
        f'{evidence}'
    )


def frame_prompt_impl(query: str, position_sec: float) -> str:
    return (
        f'This keyframe is at {position_sec:.1f}s in a video. For the question "{query}", '
        'describe it in 2-3 sentences: who is visible and what they are doing, the setting, '
        'any visible text or signage, facial expressions and gestures, who appears to be '
        'speaking, and the emotional tone. Describe only what is visible; do not invent '
        'names or plot details.'
    )


@pxt.udf
def native_prompt(query: str) -> str:
    return native_prompt_impl(query)


@pxt.udf
def synthesis_prompt(query: str, evidence: str, duration_sec: float, attached: list) -> str:
    """`attached` holds the keyframes whose images accompany the prompt."""
    return synthesis_prompt_impl(query, evidence, duration_sec, len(attached))


@pxt.udf
def frame_prompt(query: str, position_sec: float) -> str:
    return frame_prompt_impl(query, position_sec)
