"""MCQ / frame prompt helpers for Video-MME (Pixeltable UDFs + plain functions)."""

from __future__ import annotations

import pixeltable as pxt

from video_benchmark.videomme.scoring import mcq_frame_prompt, mcq_prompt


@pxt.udf
def videomme_frame_prompt(position_sec: float | None = None) -> str:
    return mcq_frame_prompt(position_sec)


@pxt.udf
def videomme_mcq_prompt(question: str, options: list | None) -> str:
    return mcq_prompt(question, list(options) if options else None)


def orchestrated_mcq_prompt(
    question: str,
    options: list[str] | None,
    shared_context: str,
    video_duration_sec: float | None = None,
) -> str:
    duration_note = ''
    if video_duration_sec and float(video_duration_sec) > 0:
        duration_note = f'The video is approximately {float(video_duration_sec):.0f} seconds long. '
    return (
        f'{duration_note}'
        'Using ONLY the evidence below (transcript + keyframe notes), answer the multiple-choice '
        'question. Choose exactly one of A, B, C, or D.\n\n'
        f'{mcq_prompt(question, options)}\n\n'
        f'Evidence:\n{shared_context.strip()}'
    )
