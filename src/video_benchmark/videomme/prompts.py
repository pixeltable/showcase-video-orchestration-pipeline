"""Video-MME prompts. Native and orchestrated paths share the question block word for word."""

from __future__ import annotations

import re

import pixeltable as pxt

ANSWER_FORMAT = (
    'Reason briefly if needed, then end with a single line exactly in this format:\nAnswer: X'
)


def format_options(options: list[str]) -> str:
    lines = []
    for i, option in enumerate(options):
        text = str(option).strip()
        # Video-MME options usually carry their letter already ("A. ...").
        lines.append(text if re.match(r'^[A-D][.):]\s*', text) else f'{chr(65 + i)}. {text}')
    return '\n'.join(lines)


def question_block_impl(question: str, options: list[str]) -> str:
    return (
        'Answer the multiple-choice question about the video. Choose exactly one of A, B, C, '
        f'or D.\n\nQuestion: {question.strip()}\n\nOptions:\n{format_options(options)}\n\n'
        f'{ANSWER_FORMAT}'
    )


def orchestrated_prompt_impl(
    question: str, options: list[str], evidence: str, duration_sec: float, n_images: int = 0
) -> str:
    images = f' {n_images} of the keyframes are attached as images above.' if n_images else ''
    return (
        f'The evidence below was extracted from a video about {duration_sec:.0f} seconds long: '
        'a timestamped audio transcript and descriptions of keyframes sampled across the whole '
        f'video.{images} Treat it as your view of the video.\n\n'
        f'{question_block_impl(question, options)}\n\nEvidence:\n{evidence}'
    )


def frame_prompt_impl(position_sec: float) -> str:
    """Query-agnostic, so one video's captions serve all of its questions."""
    return (
        f'This keyframe is at {position_sec:.1f}s in a video. Describe it in 2-3 sentences for '
        'later multiple-choice questions: who is visible, what they are doing, the setting, '
        'any on-screen text, and notable actions. Describe only what is visible.'
    )


@pxt.udf
def question_block(question: str, options: list) -> str:
    return question_block_impl(question, options)


@pxt.udf
def orchestrated_prompt(
    question: str, options: list, evidence: str, duration_sec: float, attached: list
) -> str:
    """`attached` holds the keyframes whose images accompany the prompt."""
    return orchestrated_prompt_impl(question, options, evidence, duration_sec, len(attached))


@pxt.udf
def frame_prompt(position_sec: float) -> str:
    return frame_prompt_impl(position_sec)
