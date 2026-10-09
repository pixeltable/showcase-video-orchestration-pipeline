"""Fairness: every answer-writing call gets the same question and the same guidance."""

from __future__ import annotations

from video_benchmark.prompts import (
    ANSWER_GUIDANCE,
    frame_prompt_impl,
    native_prompt_impl,
    synthesis_prompt_impl,
)
from video_benchmark.videomme.prompts import (
    format_options,
    orchestrated_prompt_impl,
    question_block_impl,
)

QUERY = 'Summarize the main activities, speakers, and visual events in this video.'


def test_native_and_synthesis_share_question_and_guidance():
    native = native_prompt_impl(QUERY)
    synthesis = synthesis_prompt_impl(QUERY, '<audio_transcript>...</audio_transcript>', 255.0, 8)
    for prompt in (native, synthesis):
        assert f'Question: {QUERY}' in prompt
        assert ANSWER_GUIDANCE in prompt
    assert '8 of the keyframes are attached' in synthesis
    assert 'attached' not in synthesis_prompt_impl(QUERY, 'ev', 255.0, 0)


def test_prompts_carry_no_clip_specific_hints():
    # Scored beats of the Pursuit clip must come from the video, not from the prompt.
    text = ' '.join(
        [
            native_prompt_impl(QUERY),
            synthesis_prompt_impl(QUERY, '', 1.0, 0),
            frame_prompt_impl(QUERY, 1.0),
        ]
    ).lower()
    for hint in ('pants', 'salary', 'tonight', 'jay', 'chris', 'internship', 'punchline'):
        assert hint not in text


def test_mcq_prompts_share_the_question_block():
    options = ['A. red', 'B. blue', 'green', 'D) yellow']
    block = question_block_impl('Which color?', options)
    assert format_options(options).splitlines() == ['A. red', 'B. blue', 'C. green', 'D) yellow']
    orchestrated = orchestrated_prompt_impl('Which color?', options, 'EVIDENCE', 90.0, 2)
    assert block in orchestrated
    assert orchestrated.endswith('Evidence:\nEVIDENCE')
    assert '2 of the keyframes are attached' in orchestrated
