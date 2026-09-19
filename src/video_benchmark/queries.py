"""Pixeltable @pxt.query helpers — register after pipeline views exist."""

from __future__ import annotations

import pixeltable as pxt
from pixeltable.func import QueryTemplateFunction

_gemini_frame_insights: QueryTemplateFunction | None = None
_gemini_frame_batch_inputs: QueryTemplateFunction | None = None
_gemini_frame_images: QueryTemplateFunction | None = None
_gemini_audio_transcripts: QueryTemplateFunction | None = None
_oss_frame_insights: QueryTemplateFunction | None = None
_oss_audio_transcripts: QueryTemplateFunction | None = None


def register(
    keyframes: pxt.Table,
    audio_chunks: pxt.Table,
    *,
    oss_asr: str = 'whisperx',
    include_gemini: bool = True,
    include_oss: bool = True,
    batched_vision: bool = False,
) -> None:
    global _gemini_frame_insights, _gemini_frame_batch_inputs, _gemini_frame_images
    global _gemini_audio_transcripts, _oss_frame_insights, _oss_audio_transcripts

    asr_mode = oss_asr.strip().lower()
    use_gemini_asr = asr_mode == 'gemini'
    use_whisperx = asr_mode == 'whisperx'

    if include_gemini:
        if not batched_vision:

            @pxt.query
            def gemini_frame_insights(query: str):
                # Text-only rollup — do not include frame images here (breaks JSON context).
                # Filter by parent query: unscoped queries return all child rows per parent.
                return (
                    keyframes.where(keyframes.query == query)
                    .order_by(keyframes.global_position_ms)
                    .select(
                        pos_msec=keyframes.global_position_ms,
                        segment_start=keyframes.segment_start,
                        frame_insight=keyframes.gemini_frame_insight,
                        frame_cost=keyframes.gemini_frame_cost,
                    )
                )

            _gemini_frame_insights = gemini_frame_insights
        else:
            _gemini_frame_insights = None

        @pxt.query
        def gemini_frame_batch_inputs(query: str):
            return (
                keyframes.where(keyframes.query == query)
                .order_by(keyframes.global_position_ms)
                .select(
                    pos_msec=keyframes.global_position_ms,
                    segment_start=keyframes.segment_start,
                    frame=keyframes.frame,
                )
            )

        @pxt.query
        def gemini_frame_images(query: str):
            """Keyframe images for Path 2 multimodal synthesis (matched by pos_msec)."""
            return (
                keyframes.where(keyframes.query == query)
                .order_by(keyframes.global_position_ms)
                .select(
                    pos_msec=keyframes.global_position_ms,
                    frame=keyframes.frame,
                )
            )

        @pxt.query
        def gemini_audio_transcripts(query: str):
            return (
                audio_chunks.where(audio_chunks.query == query)
                .order_by(audio_chunks.segment_start)
                .select(
                    segment_lines=audio_chunks.gemini_transcript_lines,
                )
            )

        _gemini_frame_batch_inputs = gemini_frame_batch_inputs
        _gemini_frame_images = gemini_frame_images
        _gemini_audio_transcripts = gemini_audio_transcripts

    if include_oss:

        @pxt.query
        def oss_frame_insights(query: str):
            return (
                keyframes.where(keyframes.query == query)
                .order_by(keyframes.global_position_ms)
                .select(
                    pos_msec=keyframes.global_position_ms,
                    segment_start=keyframes.segment_start,
                    frame_insight=keyframes.oss_frame_insight,
                )
            )

        @pxt.query
        def oss_audio_transcripts(query: str):
            if use_gemini_asr:
                return (
                    audio_chunks.where(audio_chunks.query == query)
                    .order_by(audio_chunks.segment_start)
                    .select(
                        segment_lines=audio_chunks.gemini_transcript_lines,
                    )
                )
            if use_whisperx:
                return (
                    audio_chunks.where(audio_chunks.query == query)
                    .order_by(audio_chunks.segment_start)
                    .select(
                        segment_lines=audio_chunks.whisperx_segment_lines,
                    )
                )
            return (
                audio_chunks.where(audio_chunks.query == query)
                .order_by(audio_chunks.segment_start)
                .select(
                    segment_lines=audio_chunks.whisper_segment_lines,
                )
            )

        _oss_frame_insights = oss_frame_insights
        _oss_audio_transcripts = oss_audio_transcripts


def gemini_frame_insights(query=None):
    if _gemini_frame_insights is None:
        raise RuntimeError('queries.register() must run before gemini_frame_insights()')
    if query is None:
        raise TypeError('gemini_frame_insights(query) requires parent query column')
    return _gemini_frame_insights(query)


def gemini_frame_batch_inputs(query=None):
    if _gemini_frame_batch_inputs is None:
        raise RuntimeError('queries.register() must run before gemini_frame_batch_inputs()')
    if query is None:
        raise TypeError('gemini_frame_batch_inputs(query) requires parent query column')
    return _gemini_frame_batch_inputs(query)


def gemini_frame_images(query=None):
    if _gemini_frame_images is None:
        raise RuntimeError('queries.register() must run before gemini_frame_images()')
    if query is None:
        raise TypeError('gemini_frame_images(query) requires parent query column')
    return _gemini_frame_images(query)


def gemini_audio_transcripts(query=None):
    if _gemini_audio_transcripts is None:
        raise RuntimeError('queries.register() must run before gemini_audio_transcripts()')
    if query is None:
        raise TypeError('gemini_audio_transcripts(query) requires parent query column')
    return _gemini_audio_transcripts(query)


def oss_frame_insights(query=None):
    if _oss_frame_insights is None:
        raise RuntimeError('queries.register() must run before oss_frame_insights()')
    if query is None:
        raise TypeError('oss_frame_insights(query) requires parent query column')
    return _oss_frame_insights(query)


def oss_audio_transcripts(query=None):
    if _oss_audio_transcripts is None:
        raise RuntimeError('queries.register() must run before oss_audio_transcripts()')
    if query is None:
        raise TypeError('oss_audio_transcripts(query) requires parent query column')
    return _oss_audio_transcripts(query)
