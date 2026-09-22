"""Video-MME catalog as TableModel classes (Pixeltable 0.7+)."""

# TableModel class bodies bind iterator/base columns that ruff cannot see.
# ruff: noqa: F821

from __future__ import annotations

import pixeltable as pxt
from pixeltable.functions.audio import audio_splitter
from pixeltable.functions.gemini import generate_content
from pixeltable.functions.gemini import transcribe as gemini_transcribe
from pixeltable.functions.video import (
    extract_audio,
    frame_iterator,
    get_duration,
    scene_detect_content,
)

from video_benchmark.config import AUDIO_SPLIT_FULL_DURATION_SEC, BenchmarkConfig
from video_benchmark.oss_providers import oss_frame_insight_expr
from video_benchmark.udfs import (
    GEMINI_25_FLASH_INPUT_PER_M,
    asr_cost_from_transcripts,
    assemble_mcq_evidence,
    compact_frame_context,
    dedupe_frame_context,
    estimate_image_tokens,
    estimate_text_tokens,
    gemini_output_tokens,
    gemini_prompt_tokens,
    gemini_text,
    gemini_transcribe_prompt,
    merge_transcript_segment_lists,
    parse_diarized_transcript,
    resolved_gemini_cost,
    scene_cut_segment_times,
    select_scene_frames,
    summarize_frame_context,
    vision_cost_from_frames,
)
from video_benchmark.videomme.prompts import videomme_frame_prompt

CATALOG_DIR = 'videomme'
OSS_FRAME_QUERY = (
    'Describe this keyframe for later multiple-choice answering about the video: '
    'who is visible, actions, setting, on-screen text. Describe only what is visible.'
)


def build_core_models(config: BenchmarkConfig) -> type:
    TableModel = pxt.model_base()
    threshold = config.scene_detect_threshold
    min_seg = config.min_segment_duration
    fallback = config.segment_fallback_window_sec
    gemini_model = config.gemini_model
    sample_count = max(1, int(config.vision_sample_keyframes or 24))

    class Videos(TableModel, name='videos'):
        video_id = pxt.Column(type=pxt.String, primary_key=True)
        video: pxt.Video
        duration: pxt.String
        domain: pxt.String
        url: pxt.String
        scene_cuts = scene_detect_content(video, threshold=threshold)
        video_duration_sec = get_duration(video)
        segment_times = scene_cut_segment_times(
            scene_cuts, video_duration_sec, min_seg, fallback
        )
        audio = extract_audio(video, format='mp3')

    class AudioChunks(
        TableModel,
        name='audio_chunks',
        base=Videos,
        iterator=audio_splitter(audio=Videos.audio, duration=AUDIO_SPLIT_FULL_DURATION_SEC),
    ):
        gemini_chunk_transcript = gemini_transcribe(
            audio=audio_segment,
            model=gemini_model,
            prompt=gemini_transcribe_prompt(),
        )
        gemini_transcript_lines = parse_diarized_transcript(
            gemini_chunk_transcript, segment_start
        )

    class Keyframes(
        TableModel,
        name='keyframes',
        base=Videos,
        iterator=frame_iterator(Videos.video, num_frames=sample_count),
    ):
        frame_position_sec = frame_attrs['time'].astype(pxt.Float)
        segment_start = 0.0
        global_position_sec = frame_position_sec.astype(pxt.Float)
        global_position_ms = (global_position_sec * 1000.0).astype(pxt.Float)
        gemini_frame_response = generate_content(
            model=gemini_model,
            contents=[frame, videomme_frame_prompt(global_position_sec)],
        )
        gemini_frame_insight = gemini_text(gemini_frame_response)
        gemini_frame_input_tokens = estimate_image_tokens('videomme')
        gemini_frame_output_tokens = estimate_text_tokens(gemini_frame_insight)
        gemini_frame_actual_input_tokens = gemini_prompt_tokens(gemini_frame_response)
        gemini_frame_actual_output_tokens = gemini_output_tokens(gemini_frame_response)
        gemini_frame_cost = resolved_gemini_cost(
            gemini_frame_actual_input_tokens,
            gemini_frame_actual_output_tokens,
            gemini_frame_input_tokens,
            gemini_frame_output_tokens,
            GEMINI_25_FLASH_INPUT_PER_M,
        )

    return TableModel


def build_parent_models(
    config: BenchmarkConfig,
    *,
    frame_insights,
    audio_transcripts,
) -> type:
    TableModel = pxt.model_base()
    threshold = config.scene_detect_threshold
    min_seg = config.min_segment_duration
    fallback = config.segment_fallback_window_sec

    class Videos(TableModel, name='videos'):
        video_id = pxt.Column(type=pxt.String, primary_key=True)
        video: pxt.Video
        duration: pxt.String
        domain: pxt.String
        url: pxt.String
        scene_cuts = scene_detect_content(video, threshold=threshold)
        video_duration_sec = get_duration(video)
        segment_times = scene_cut_segment_times(
            scene_cuts, video_duration_sec, min_seg, fallback
        )
        audio = extract_audio(video, format='mp3')
        gemini_frame_context = frame_insights(video_id)
        gemini_transcript_context = merge_transcript_segment_lists(audio_transcripts(video_id))
        gemini_frame_context_deduped = dedupe_frame_context(gemini_frame_context)
        if config.scene_aware_frames:
            gemini_frame_context_selected = select_scene_frames(
                gemini_frame_context_deduped,
                scene_cuts,
                config.frame_select_budget,
            )
            gemini_frame_context_summarized = summarize_frame_context(
                gemini_frame_context_selected, config.frame_context_max_entries
            )
        else:
            gemini_frame_context_summarized = summarize_frame_context(
                gemini_frame_context_deduped, config.frame_context_max_entries
            )
        shared_context = assemble_mcq_evidence(
            gemini_transcript_context,
            gemini_frame_context_summarized,
            'Gemini',
        )
        gemini_vision_track_cost = vision_cost_from_frames(gemini_frame_context)
        gemini_asr_cost = asr_cost_from_transcripts(
            gemini_transcript_context, video_duration_sec
        )

    return TableModel


def build_oss_keyframe_models(
    config: BenchmarkConfig,
    *,
    frame_insights,
    audio_transcripts,
) -> type:
    """Add oss_frame_insight on keyframes; Videos redeclares existing parent columns."""
    TableModel = pxt.model_base()
    threshold = config.scene_detect_threshold
    min_seg = config.min_segment_duration
    fallback = config.segment_fallback_window_sec
    gemini_model = config.gemini_model
    sample_count = max(1, int(config.vision_sample_keyframes or 24))

    class Videos(TableModel, name='videos'):
        video_id = pxt.Column(type=pxt.String, primary_key=True)
        video: pxt.Video
        duration: pxt.String
        domain: pxt.String
        url: pxt.String
        scene_cuts = scene_detect_content(video, threshold=threshold)
        video_duration_sec = get_duration(video)
        segment_times = scene_cut_segment_times(
            scene_cuts, video_duration_sec, min_seg, fallback
        )
        audio = extract_audio(video, format='mp3')
        gemini_frame_context = frame_insights(video_id)
        gemini_transcript_context = merge_transcript_segment_lists(audio_transcripts(video_id))
        gemini_frame_context_deduped = dedupe_frame_context(gemini_frame_context)
        if config.scene_aware_frames:
            gemini_frame_context_selected = select_scene_frames(
                gemini_frame_context_deduped,
                scene_cuts,
                config.frame_select_budget,
            )
            gemini_frame_context_summarized = summarize_frame_context(
                gemini_frame_context_selected, config.frame_context_max_entries
            )
        else:
            gemini_frame_context_summarized = summarize_frame_context(
                gemini_frame_context_deduped, config.frame_context_max_entries
            )
        shared_context = assemble_mcq_evidence(
            gemini_transcript_context,
            gemini_frame_context_summarized,
            'Gemini',
        )
        gemini_vision_track_cost = vision_cost_from_frames(gemini_frame_context)
        gemini_asr_cost = asr_cost_from_transcripts(
            gemini_transcript_context, video_duration_sec
        )

    class Keyframes(
        TableModel,
        name='keyframes',
        base=Videos,
        iterator=frame_iterator(Videos.video, num_frames=sample_count),
    ):
        frame_position_sec = frame_attrs['time'].astype(pxt.Float)
        segment_start = 0.0
        global_position_sec = frame_position_sec.astype(pxt.Float)
        global_position_ms = (global_position_sec * 1000.0).astype(pxt.Float)
        gemini_frame_response = generate_content(
            model=gemini_model,
            contents=[frame, videomme_frame_prompt(global_position_sec)],
        )
        gemini_frame_insight = gemini_text(gemini_frame_response)
        gemini_frame_input_tokens = estimate_image_tokens('videomme')
        gemini_frame_output_tokens = estimate_text_tokens(gemini_frame_insight)
        gemini_frame_actual_input_tokens = gemini_prompt_tokens(gemini_frame_response)
        gemini_frame_actual_output_tokens = gemini_output_tokens(gemini_frame_response)
        gemini_frame_cost = resolved_gemini_cost(
            gemini_frame_actual_input_tokens,
            gemini_frame_actual_output_tokens,
            gemini_frame_input_tokens,
            gemini_frame_output_tokens,
            GEMINI_25_FLASH_INPUT_PER_M,
        )
        oss_frame_insight = oss_frame_insight_expr(
            frame,
            OSS_FRAME_QUERY,
            global_position_sec,
            backend=config.oss_backend,
            vision_model=config.oss_vision_model,
            vision_repo_id=config.oss_vision_repo_id,
            vision_repo_filename=config.oss_vision_repo_filename,
            mmproj_repo_filename=config.oss_vision_mmproj_repo_filename,
            vision_chat_format=config.oss_vision_chat_format,
            ollama_host=config.ollama_host,
        )

    return TableModel


def build_oss_parent_models(
    config: BenchmarkConfig,
    *,
    frame_insights,
    audio_transcripts,
    oss_frame_insights,
) -> type:
    TableModel = pxt.model_base()
    threshold = config.scene_detect_threshold
    min_seg = config.min_segment_duration
    fallback = config.segment_fallback_window_sec

    class Videos(TableModel, name='videos'):
        video_id = pxt.Column(type=pxt.String, primary_key=True)
        video: pxt.Video
        duration: pxt.String
        domain: pxt.String
        url: pxt.String
        scene_cuts = scene_detect_content(video, threshold=threshold)
        video_duration_sec = get_duration(video)
        segment_times = scene_cut_segment_times(
            scene_cuts, video_duration_sec, min_seg, fallback
        )
        audio = extract_audio(video, format='mp3')
        gemini_frame_context = frame_insights(video_id)
        gemini_transcript_context = merge_transcript_segment_lists(audio_transcripts(video_id))
        gemini_frame_context_deduped = dedupe_frame_context(gemini_frame_context)
        if config.scene_aware_frames:
            gemini_frame_context_selected = select_scene_frames(
                gemini_frame_context_deduped,
                scene_cuts,
                config.frame_select_budget,
            )
            gemini_frame_context_summarized = summarize_frame_context(
                gemini_frame_context_selected, config.frame_context_max_entries
            )
        else:
            gemini_frame_context_summarized = summarize_frame_context(
                gemini_frame_context_deduped, config.frame_context_max_entries
            )
        shared_context = assemble_mcq_evidence(
            gemini_transcript_context,
            gemini_frame_context_summarized,
            'Gemini',
        )
        gemini_vision_track_cost = vision_cost_from_frames(gemini_frame_context)
        gemini_asr_cost = asr_cost_from_transcripts(
            gemini_transcript_context, video_duration_sec
        )
        oss_frame_context = oss_frame_insights(video_id)
        oss_frame_context_deduped = dedupe_frame_context(oss_frame_context)
        if config.scene_aware_frames:
            oss_frame_context_selected = select_scene_frames(
                oss_frame_context_deduped,
                scene_cuts,
                config.frame_select_budget,
            )
            oss_frame_context_summarized = summarize_frame_context(
                oss_frame_context_selected, config.oss_frame_context_max_entries
            )
        else:
            oss_frame_context_summarized = summarize_frame_context(
                oss_frame_context_deduped, config.oss_frame_context_max_entries
            )
        oss_frame_context_compact = compact_frame_context(
            oss_frame_context_summarized, config.oss_frame_insight_max_chars
        )
        oss_shared_context = assemble_mcq_evidence(
            gemini_transcript_context,
            oss_frame_context_compact,
            'OSS',
        )

    return TableModel
